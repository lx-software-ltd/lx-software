/**
 * Cloudflare Email Worker: fan every siutindei.com message out to the owner's
 * inbox AND the Executive Board's SES inbound address.
 *
 * Why: Cloudflare Email Routing rules deliver each address to exactly one
 * destination. Binding this Worker to the zone's catch-all keeps the owner's
 * mail client untouched while the board gets an identical copy to index
 * (docs/architecture/executive-board-tools-plan.md §5.2).
 *
 * Setup (Cloudflare dashboard, siutindei.com zone):
 *   1. Email > Email Routing > Destination addresses: add the board address
 *      from the `SiutindeiBoardMailInboundAddress` stack output
 *      (siutindei-board@inbound.lx-software.com). Cloudflare emails a
 *      verification link there; it lands in the SES inbound bucket under
 *      inbound-raw/siutindei/ — open the object once and click the link.
 *   2. Workers & Pages > Create > paste this file. Add two plain-text variables:
 *        OWNER_DESTINATION  the owner's existing verified inbox
 *        BOARD_DESTINATION  the board address from step 1
 *      Optionally SKIP_SENDERS: comma-separated addresses/domains never copied
 *      to the board (e.g. a personal address).
 *   3. Email Routing > Routing rules > Catch-all address: Action "Send to a
 *      Worker", pick this Worker. Existing per-address rules can stay; only
 *      addresses without their own rule reach the catch-all, so either delete
 *      them or point them at the Worker too.
 *
 * The board copy carries `X-Original-To` so the indexer knows which mailbox
 * (hello@, billing@, ...) the message was addressed to even when the To:
 * header is a list or a BCC.
 */

function parseList(value) {
  return String(value || "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

function senderIsSkipped(from, skipList) {
  const address = String(from || "").toLowerCase();
  const domain = address.includes("@") ? address.split("@").pop() : "";
  return skipList.some((entry) =>
    entry.startsWith("@") ? entry.slice(1) === domain : entry === address
  );
}

export default {
  async email(message, env) {
    const owner = String(env.OWNER_DESTINATION || "").trim();
    const board = String(env.BOARD_DESTINATION || "").trim();
    const skipList = parseList(env.SKIP_SENDERS);

    if (!owner) {
      // Never drop mail silently: refusing makes the sender's MTA retry/bounce.
      message.setReject("Mail routing is not configured");
      return;
    }

    const deliveries = [message.forward(owner)];
    if (board && !senderIsSkipped(message.from, skipList)) {
      const headers = new Headers();
      headers.set("X-Original-To", message.to);
      deliveries.push(message.forward(board, headers));
    }

    const results = await Promise.allSettled(deliveries);
    if (results[0].status === "rejected") {
      // The owner's copy is the one that matters; surface the failure upstream.
      throw results[0].reason;
    }
    if (results[1] && results[1].status === "rejected") {
      console.warn("board copy failed", String(results[1].reason));
    }
  },
};
