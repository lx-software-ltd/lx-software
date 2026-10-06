import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { LINKEDIN_BYTES_KEY, useLinkedIn } from "../../hooks/useLinkedIn";
import { adminFetchJson, getAdminApiErrorMessage } from "../../lib/apiAdminClient";
import { DRAFT_RECORD_ID } from "../../lib/expandedRecord";
import {
  guardrails,
  hasBlockingGuardrail,
  hookText,
  isLinkedInPostUrl,
  linkedInShareUrl,
  pillarLabel,
  type LinkedInPost,
  type LinkedInDraftSettings,
} from "../../lib/linkedinModel";
import {
  AdminCell,
  AdminCreateButton,
  AdminDataTable,
  AdminDataTableCellMeta,
  AdminDataTableEmptyRow,
  AdminEditorPanel,
  AdminExpandableRow,
  AdminField,
  AdminFieldGrid,
  AdminFilterBar,
  AdminFilterField,
  AdminRecordTable,
  AdminRowActions,
  ConfirmDialog,
} from "../ui";

const COLUMNS = [
  { key: "hook", header: "Hook" },
  { key: "pillar", header: "Pillar", priority: "secondary" as const },
  { key: "slot", header: "Slot", priority: "secondary" as const },
  { key: "status", header: "Status", priority: "secondary" as const },
  { key: "ops", header: <span className="visually-hidden">Operations</span>, className: "text-end" },
];

function errorText(err: unknown): string | null {
  if (!err) return null;
  return getAdminApiErrorMessage(err) ?? (err instanceof Error ? err.message : "Request failed.");
}

function statusLabel(status: string): string {
  if (status === "drafted") return "Draft";
  if (status === "approved") return "Approved";
  if (status === "published") return "Posted";
  return status;
}

export function LinkedInDraftsSection({
  settings,
  enabled,
}: {
  readonly settings: LinkedInDraftSettings | undefined;
  readonly enabled: boolean;
}) {
  const linkedIn = useLinkedIn();
  const posts = (linkedIn.posts.data?.items ?? []).filter((row) => row.status === "drafted" || row.status === "approved");
  const [params, setParams] = useSearchParams();
  const openId = params.get("linkedin-post");
  const [pillar, setPillar] = useState("");
  const [status, setStatus] = useState("");
  const [filter, setFilter] = useState("");
  const [archiveId, setArchiveId] = useState<string | null>(null);
  const activeSettings = settings;

  const visible = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return posts.filter((row) => {
      if (pillar && row.pillar !== pillar) return false;
      if (status && row.status !== status) return false;
      if (!q) return true;
      return `${row.body} ${row.pillar}`.toLowerCase().includes(q);
    });
  }, [filter, pillar, posts, status]);

  useEffect(() => {
    if (!openId || openId === DRAFT_RECORD_ID || linkedIn.posts.isLoading) return;
    if (!posts.some((row) => row.postId === openId)) {
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("linkedin-post");
        return next;
      }, { replace: true });
    }
  }, [linkedIn.posts.isLoading, openId, posts, setParams]);

  function setOpen(id: string | null) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (id) next.set("linkedin-post", id);
      else next.delete("linkedin-post");
      return next;
    }, { replace: true });
  }

  async function copyText(text: string) {
    await navigator.clipboard.writeText(text);
  }

  return (
    <>
      <AdminRecordTable
        label="LinkedIn drafts"
        filters={
          <AdminFilterBar
            beforeCreate={
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm admin-create-btn"
                disabled={!enabled || linkedIn.generate.isPending}
                onClick={() => void linkedIn.generate.mutate({})}
              >
                {linkedIn.generate.isPending ? "Generating…" : "Generate drafts"}
              </button>
            }
            create={<AdminCreateButton label="New post" disabled={!enabled} onClick={() => setOpen(DRAFT_RECORD_ID)} />}
          >
            <AdminFilterField label="Filter" htmlFor="linkedin-filter">
              <input
                id="linkedin-filter"
                className="form-control form-control-sm"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Search drafts"
              />
            </AdminFilterField>
            <AdminFilterField label="Pillar" htmlFor="linkedin-pillar" hideLabel>
              <select
                id="linkedin-pillar"
                className="form-select form-select-sm"
                value={pillar}
                onChange={(event) => setPillar(event.target.value)}
              >
                <option value="">All pillars</option>
                {(activeSettings?.pillars ?? []).map((id) => (
                  <option key={id} value={id}>{pillarLabel(id)}</option>
                ))}
              </select>
            </AdminFilterField>
            <AdminFilterField label="Status" htmlFor="linkedin-status" hideLabel>
              <select
                id="linkedin-status"
                className="form-select form-select-sm"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                <option value="">All statuses</option>
                <option value="drafted">Draft</option>
                <option value="approved">Approved</option>
              </select>
            </AdminFilterField>
          </AdminFilterBar>
        }
      >
        {linkedIn.generate.isError ? (
          <p className="text-danger small mb-2">{errorText(linkedIn.generate.error)}</p>
        ) : null}
        <AdminDataTable columns={COLUMNS} bare tableClassName="admin-table-compact">
          {visible.length === 0 && openId !== DRAFT_RECORD_ID ? (
            <AdminDataTableEmptyRow colSpan={COLUMNS.length} message="No drafts yet." />
          ) : (
            visible.map((row) => (
              <DraftRow
                key={row.postId}
                post={row}
                settings={activeSettings}
                expanded={openId === row.postId}
                enabled={enabled}
                onToggle={() => setOpen(openId === row.postId ? null : row.postId)}
                onArchive={() => setArchiveId(row.postId)}
                onCopy={() => void copyText(row.body)}
                onShare={() => window.open(linkedInShareUrl(row.body), "_blank", "noopener,noreferrer")}
              />
            ))
          )}
          {openId === DRAFT_RECORD_ID && activeSettings ? (
            <DraftEditorRow
              settings={activeSettings}
              enabled={enabled}
              onClose={() => setOpen(null)}
            />
          ) : null}
        </AdminDataTable>
      </AdminRecordTable>
      <ConfirmDialog
        open={archiveId !== null}
        title="Archive this draft?"
        body="The draft leaves the queue. A posted copy on LinkedIn is unchanged."
        confirmLabel="Archive"
        tone="danger"
        onCancel={() => setArchiveId(null)}
        onConfirm={() => {
          if (archiveId) void linkedIn.act.mutate({ postId: archiveId, action: "archive" });
          setArchiveId(null);
          setOpen(null);
        }}
      />
    </>
  );
}

function DraftRow({
  post,
  settings,
  expanded,
  enabled,
  onToggle,
  onArchive,
  onCopy,
  onShare,
}: {
  readonly post: LinkedInPost;
  readonly settings: LinkedInDraftSettings | undefined;
  readonly expanded: boolean;
  readonly enabled: boolean;
  readonly onToggle: () => void;
  readonly onArchive: () => void;
  readonly onCopy: () => void;
  readonly onShare: () => void;
}) {
  const linkedIn = useLinkedIn();
  const hook = hookText(post.body);
  return (
    <AdminExpandableRow
      colSpan={COLUMNS.length}
      expanded={expanded}
      onToggle={onToggle}
      editor={
        settings ? (
          <PostEditor
            post={post}
            settings={settings}
            enabled={enabled}
            saving={linkedIn.updatePost.isPending || linkedIn.act.isPending}
            error={errorText(linkedIn.updatePost.error) ?? errorText(linkedIn.act.error)}
            onSave={async (body, approve) => {
              await linkedIn.updatePost.mutateAsync({ postId: post.postId, body });
              if (approve) await linkedIn.act.mutateAsync({ postId: post.postId, action: "approve" });
            }}
            onMarkPosted={async (url) => {
              await linkedIn.act.mutateAsync({ postId: post.postId, action: "mark-posted", body: { url } });
            }}
          />
        ) : null
      }
    >
      <AdminCell column="hook">
        {hook || "Untitled"}
        <AdminDataTableCellMeta>
          {statusLabel(post.status)}
          {post.slotAt ? ` · ${post.slotAt.slice(0, 10)}` : ""}
        </AdminDataTableCellMeta>
      </AdminCell>
      <AdminCell column="pillar">{pillarLabel(post.pillar)}</AdminCell>
      <AdminCell column="slot">{post.slotAt ? post.slotAt.slice(0, 16).replace("T", " ") : "—"}</AdminCell>
      <AdminCell column="status">{statusLabel(post.status)}</AdminCell>
      <AdminCell column="ops" className="text-end">
        <AdminRowActions
          actions={[
            { id: "share", label: "Open share box", iconClassName: "bi-box-arrow-up-right", onClick: onShare },
            { id: "copy", label: "Copy post text", iconClassName: "bi-clipboard", onClick: onCopy },
            {
              id: "unapprove",
              label: "Unapprove",
              iconClassName: "bi-arrow-counterclockwise",
              hidden: post.status !== "approved" || !enabled,
              onClick: () => void linkedIn.act.mutate({ postId: post.postId, action: "unapprove" }),
            },
            {
              id: "regenerate",
              label: "Regenerate",
              iconClassName: "bi-arrow-repeat",
              hidden: !enabled,
              onClick: () => void linkedIn.regenerate.mutate(post.postId),
            },
            {
              id: "redraw-picture",
              label: "Redraw picture",
              iconClassName: "bi-image",
              hidden:
                !enabled ||
                !settings?.imagesEnabled ||
                post.status === "published" ||
                post.status === "archived",
              onClick: () =>
                void linkedIn.redrawImage.mutate({
                  postId: post.postId,
                  scene: post.image?.scene ?? "",
                  caption: post.image?.caption ?? "",
                  expression: post.image?.expression ?? "",
                }),
            },
            { id: "archive", label: "Archive", iconClassName: "bi-archive", danger: true, onClick: onArchive },
          ]}
        />
      </AdminCell>
    </AdminExpandableRow>
  );
}

(DraftRow as { recordGroup?: boolean }).recordGroup = true;

function DraftEditorRow({
  settings,
  enabled,
  onClose,
}: {
  readonly settings: LinkedInDraftSettings;
  readonly enabled: boolean;
  readonly onClose: () => void;
}) {
  const linkedIn = useLinkedIn();
  return (
    <AdminExpandableRow
      colSpan={COLUMNS.length}
      expanded
      onToggle={onClose}
      editor={
        <PostEditor
          post={null}
          settings={settings}
          enabled={enabled}
          saving={linkedIn.createPost.isPending}
          error={errorText(linkedIn.createPost.error)}
          onSave={async (body) => {
            await linkedIn.createPost.mutateAsync(body);
            onClose();
          }}
          onMarkPosted={async () => undefined}
        />
      }
    >
      <AdminCell column="hook">New post</AdminCell>
      <AdminCell column="pillar">—</AdminCell>
      <AdminCell column="slot">—</AdminCell>
      <AdminCell column="status">Draft</AdminCell>
      <AdminCell column="ops" />
    </AdminExpandableRow>
  );
}

(DraftEditorRow as { recordGroup?: boolean }).recordGroup = true;

function PostEditor({
  post,
  settings,
  enabled,
  saving,
  error,
  onSave,
  onMarkPosted,
}: {
  readonly post: LinkedInPost | null;
  readonly settings: LinkedInDraftSettings;
  readonly enabled: boolean;
  readonly saving: boolean;
  readonly error: string | null;
  readonly onSave: (body: Partial<LinkedInPost>, approve: boolean) => Promise<void>;
  readonly onMarkPosted: (url: string) => Promise<void>;
}) {
  const [body, setBody] = useState(post?.body ?? "");
  const [firstComment, setFirstComment] = useState(post?.firstComment ?? "");
  const [pillar, setPillar] = useState(post?.pillar ?? settings.pillars[0] ?? "architecture");
  const [hashtags, setHashtags] = useState((post?.hashtags ?? []).join(" "));
  const [marking, setMarking] = useState(false);
  const [postedUrl, setPostedUrl] = useState("");
  const [pictureDraft, setPictureDraft] = useState<{
    id: string;
    scene: string;
    caption: string;
    expression: string;
  } | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const linkedIn = useLinkedIn();
  const pictureId = post?.postId ?? "";
  const picture = pictureDraft?.id === pictureId ? pictureDraft : null;
  const scene = picture?.scene ?? post?.image?.scene ?? "";
  const caption = picture?.caption ?? post?.image?.caption ?? "";
  const expression = picture?.expression ?? post?.image?.expression ?? "";
  const tags = hashtags.split(/[\s,]+/).map((tag) => tag.replace(/^#/, "")).filter(Boolean);
  const findings = guardrails(body, firstComment, tags, settings);
  const blocked = hasBlockingGuardrail(findings);
  const dirty =
    body !== (post?.body ?? "") ||
    firstComment !== (post?.firstComment ?? "") ||
    pillar !== (post?.pillar ?? settings.pillars[0] ?? "architecture") ||
    tags.join(" ") !== (post?.hashtags ?? []).join(" ");
  const formId = `linkedin-post-${post?.postId ?? "new"}`;
  const hook = hookText(body);
  const rest = body.trim().slice(hook.length).trim();
  const submitLabel = !post
    ? "Add post"
    : marking
      ? "Mark posted"
      : blocked || post.status === "approved" || dirty
        ? "Update draft"
        : "Approve";

  return (
    <div className="row g-3">
      <div className="col-12 col-lg-7">
        <AdminEditorPanel
          formId={formId}
          error={localError ?? error}
          submitLabel={submitLabel}
          isSaving={saving}
          disabled={!enabled}
          onSubmit={(event) => {
            event.preventDefault();
            if (!enabled) return;
            if (marking) {
              if (!isLinkedInPostUrl(postedUrl)) {
                setLocalError("Paste the linkedin.com URL of the live post.");
                return;
              }
              setLocalError(null);
              void onMarkPosted(postedUrl);
              return;
            }
            setLocalError(null);
            const approve = Boolean(post) && !blocked && post?.status !== "approved" && !dirty;
            void onSave({ body, firstComment, pillar, hashtags: tags }, approve);
          }}
        >
          <AdminFieldGrid columns={1}>
            <AdminField label="Post" htmlFor={`${formId}-body`}>
              <textarea
                id={`${formId}-body`}
                className="form-control"
                rows={8}
                value={body}
                maxLength={3000}
                aria-describedby={`${formId}-count`}
                onChange={(event) => setBody(event.target.value)}
              />
              <p id={`${formId}-count`} className="form-text mb-0">
                {body.length} / 3000 · first line {hook.length} / 210
              </p>
            </AdminField>
            <AdminField label="First comment" htmlFor={`${formId}-comment`}>
              <textarea
                id={`${formId}-comment`}
                className="form-control"
                rows={2}
                value={firstComment}
                maxLength={1250}
                onChange={(event) => setFirstComment(event.target.value)}
              />
            </AdminField>
            <AdminField label="Pillar" htmlFor={`${formId}-pillar`}>
              <select
                id={`${formId}-pillar`}
                className="form-select"
                value={pillar}
                onChange={(event) => setPillar(event.target.value)}
              >
                {settings.pillars.map((id) => (
                  <option key={id} value={id}>{pillarLabel(id)}</option>
                ))}
              </select>
            </AdminField>
            <AdminField label="Hashtags" htmlFor={`${formId}-tags`}>
              <input
                id={`${formId}-tags`}
                className="form-control"
                value={hashtags}
                onChange={(event) => setHashtags(event.target.value)}
              />
            </AdminField>
            {post ? (
              <AdminField label="Picture" htmlFor={`${formId}-image`}>
                {post.image?.status === "pending" ? <p className="small mb-2">Drawing…</p> : null}
                {post.image?.status === "failed" ? (
                  <p className="small text-danger mb-2">{post.image.error || "The picture failed."}</p>
                ) : null}
                {post.imageNote ? <p className="small text-warning mb-2">{post.imageNote}</p> : null}
                {post.image?.contentType ? (
                  <PostPicture
                    postId={post.postId}
                    alt={post.image.caption || "Draft picture"}
                    version={`${post.updatedAt ?? ""}:${post.image.status ?? ""}`}
                  />
                ) : null}
                {settings.imagesEnabled ? (
                  <>
                <AdminField label="Scene" htmlFor={`${formId}-scene`}>
                  <textarea
                    id={`${formId}-scene`}
                    className="form-control"
                    rows={2}
                    maxLength={400}
                    value={scene}
                    onChange={(event) =>
                      setPictureDraft({ id: pictureId, scene: event.target.value, caption, expression })
                    }
                  />
                </AdminField>
                <AdminField label="Expression" htmlFor={`${formId}-expression`}>
                  <input
                    id={`${formId}-expression`}
                    className="form-control"
                    maxLength={80}
                    value={expression}
                    onChange={(event) =>
                      setPictureDraft({ id: pictureId, scene, caption, expression: event.target.value })
                    }
                  />
                  <p className="form-text mb-0">Two to five words for the face in this moment. A smile only when the moment earns it.</p>
                </AdminField>
                <AdminField label="Caption" htmlFor={`${formId}-caption`}>
                  <input
                    id={`${formId}-caption`}
                    className="form-control"
                    maxLength={140}
                    value={caption}
                    onChange={(event) =>
                      setPictureDraft({ id: pictureId, scene, caption: event.target.value, expression })
                    }
                  />
                  <p className="form-text mb-0">Spoken line, drawn inside the bottom of the picture. Also the alt text.</p>
                </AdminField>
                <button
                  type="button"
                  className="btn btn-outline-secondary btn-sm mt-2"
                  disabled={!enabled || post.image?.status === "pending" || linkedIn.redrawImage.isPending}
                  onClick={() => {
                    setLocalError(null);
                    void linkedIn.redrawImage.mutateAsync({ postId: post.postId, scene, caption, expression }).catch((caught: unknown) => {
                      setLocalError(caught instanceof Error ? caught.message : "Could not redraw the picture.");
                    });
                  }}
                >
                  {post.image?.status === "pending" || linkedIn.redrawImage.isPending ? "Drawing…" : "Redraw picture"}
                </button>
                  </>
                ) : null}
                <input
                  id={`${formId}-image`}
                  className="form-control"
                  type="file"
                  accept="image/png,image/jpeg"
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (!file) return;
                    if (file.size > 1_500_000) {
                      setLocalError("The image must be under 1.5 MB.");
                      return;
                    }
                    const reader = new FileReader();
                    reader.onload = () => {
                      const dataBase64 = String(reader.result ?? "").split(",")[1] ?? "";
                      setLocalError(null);
                      void linkedIn.uploadImage.mutateAsync({
                        postId: post.postId,
                        contentType: file.type,
                        dataBase64,
                      }).catch((caught: unknown) => {
                        setLocalError(caught instanceof Error ? caught.message : "Could not attach the image.");
                      });
                    };
                    reader.readAsDataURL(file);
                  }}
                />
                {post.image?.contentType ? (
                  <button
                    type="button"
                    className="btn btn-link btn-sm px-0"
                    onClick={() => void linkedIn.deleteImage.mutate(post.postId)}
                  >
                    Remove image
                  </button>
                ) : null}
              </AdminField>
            ) : (
              <p className="text-muted small mb-0">Save the draft, then attach an image.</p>
            )}
            {marking ? (
              <AdminField label="LinkedIn URL" htmlFor={`${formId}-url`}>
                <input
                  id={`${formId}-url`}
                  className="form-control"
                  value={postedUrl}
                  placeholder="https://www.linkedin.com/feed/update/…"
                  onChange={(event) => setPostedUrl(event.target.value)}
                />
              </AdminField>
            ) : null}
          </AdminFieldGrid>
          {post?.publishError ? (
            <p className="text-danger small mt-3 mb-0">{post.publishError}</p>
          ) : null}
          {findings.length > 0 ? (
            <ul className="small mt-3 mb-0">
              {findings.map((row) => (
                <li key={`${row.code}-${row.detail}`} className={row.severity === "error" ? "text-danger" : "text-warning"}>
                  {row.detail}
                </li>
              ))}
            </ul>
          ) : null}
          {post && !marking ? (
            <button type="button" className="btn btn-link btn-sm px-0" onClick={() => setMarking(true)}>
              Mark posted
            </button>
          ) : null}
        </AdminEditorPanel>
      </div>
      <div className="col-12 col-lg-5">
        <p className="admin-eyebrow mb-2">Preview</p>
        <div className="border rounded p-3" aria-label="Post preview">
          <p className="fw-semibold mb-2">{hook || "First line"}</p>
          <p className="small text-muted mb-0" style={{ whiteSpace: "pre-wrap" }}>{rest}</p>
          {firstComment ? <p className="small mt-3 mb-0">First comment: {firstComment}</p> : null}
        </div>
      </div>
    </div>
  );
}

function PostPicture({ postId, alt, version }: { readonly postId: string; readonly alt: string; readonly version: string }) {
  const query = useQuery({
    queryKey: [...LINKEDIN_BYTES_KEY, "post", postId, version] as const,
    queryFn: () =>
      adminFetchJson<{ contentType: string; dataBase64: string }>(`/lx-software/linkedin/posts/${postId}/image`),
    retry: false,
    staleTime: Infinity,
  });
  if (!query.data) return null;
  return (
    <img
      src={`data:${query.data.contentType};base64,${query.data.dataBase64}`}
      alt={alt}
      className="img-fluid border mb-2"
    />
  );
}
