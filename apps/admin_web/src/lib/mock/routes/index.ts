import type { MockRoute } from "./types";
import * as admin from "./admin";
import * as finance from "./finance";
import * as banking from "./banking";
import * as board from "./board";
import * as linkedin from "./linkedin";

const modules = { admin, finance, banking, board, linkedin };

export const mockRoutes: readonly MockRoute[] = [
  {
    pattern: /^\/lx-software\/linkedin/,
    handler: modules.linkedin.handleLinkedIn,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA0,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA1,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA2,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA3,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA4,
  },
  {
    method: "GET",
    pattern: /.*/,
    handler: modules.finance.handleF0,
  },
  {
    pattern: /.*/,
    handler: modules.finance.handleF1,
  },
  {
    pattern: /.*/,
    handler: modules.finance.handleF2,
  },
  {
    pattern: /.*/,
    handler: modules.finance.handleF3,
  },
  {
    pattern: new RegExp('^/finance/'),
    handler: modules.finance.handleF4,
  },
  {
    method: "GET",
    pattern: /.*/,
    handler: modules.finance.handleF5,
  },
  {
    method: "POST",
    pattern: /.*/,
    handler: modules.finance.handleF6,
  },
  {
    pattern: /.*/,
    handler: modules.finance.handleF7,
  },
  {
    pattern: /.*/,
    handler: modules.finance.handleF8,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA5,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA6,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA7,
  },
  {
    pattern: /.*/,
    handler: modules.admin.handleA8,
  },
  {
    pattern: /.*/,
    handler: modules.banking.handleB0,
  },
  {
    pattern: /.*/,
    handler: modules.banking.handleB1,
  },
  {
    pattern: /.*/,
    handler: modules.banking.handleB2,
  },
  {
    pattern: /.*/,
    handler: modules.banking.handleB3,
  },
  {
    pattern: /.*/,
    handler: modules.board.handleB0,
  },
  {
    method: "PUT",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/settings$'),
    handler: modules.board.handleB1,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/actions$'),
    handler: modules.board.handleB2,
  },
  {
    method: "PUT",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/actions/'),
    handler: modules.board.handleB3,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/approvals$'),
    handler: modules.board.handleB4,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/meetings$'),
    handler: modules.board.handleB5,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/tools$'),
    handler: modules.board.handleB6,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/tools/calls$'),
    handler: modules.board.handleB7,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/updates$'),
    handler: modules.board.handleB8,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/receivables$'),
    handler: modules.board.handleB9,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/mail$'),
    handler: modules.board.handleB10,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/mail/'),
    handler: modules.board.handleB11,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/mail/selftest$'),
    handler: modules.board.handleB12,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/staff$'),
    handler: modules.board.handleB13,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/staff/tick$'),
    handler: modules.board.handleB14,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/staff/'),
    handler: modules.board.handleB15,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/tasks$'),
    handler: modules.board.handleB16,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/tasks/'),
    handler: modules.board.handleB17,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/holds$'),
    handler: modules.board.handleB18,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/holds/veto\\-class$'),
    handler: modules.board.handleB19,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/holds/'),
    handler: modules.board.handleB20,
  },
  {
    method: "PUT",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/boundaries$'),
    handler: modules.board.handleB21,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/ramp$'),
    handler: modules.board.handleB22,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/ramp/'),
    handler: modules.board.handleB23,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/code/staging$'),
    handler: modules.board.handleB24,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/code/sync\\-staging$'),
    handler: modules.board.handleB25,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/preview$'),
    handler: modules.board.handleB26,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/import$'),
    handler: modules.board.handleB27,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/skip$'),
    handler: modules.board.handleB28,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/requeue$'),
    handler: modules.board.handleB29,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/reimport$'),
    handler: modules.board.handleB30,
  },
  {
    method: "GET",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/sources$'),
    handler: modules.board.handleB31,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/bulk/'),
    handler: modules.board.handleB32,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/bulk/'),
    handler: modules.board.handleB33,
  },
  {
    method: "GET",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/candidates$'),
    handler: modules.board.handleB34,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/candidates/bulk$'),
    handler: modules.board.handleB35,
  },
  {
    method: "POST",
    pattern: /.*/,
    handler: modules.admin.handleA9,
  },
  {
    method: "POST",
    pattern: /.*/,
    handler: modules.admin.handleA10,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/catalog/discovery/run$'),
    handler: modules.board.handleB36,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/code/promote$'),
    handler: modules.board.handleB37,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/review$'),
    handler: modules.board.handleB38,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/progress$'),
    handler: modules.board.handleB39,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/review/sample/'),
    handler: modules.board.handleB40,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/lessons$'),
    handler: modules.board.handleB41,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/lessons/'),
    handler: modules.board.handleB42,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/lessons/'),
    handler: modules.board.handleB43,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/breakers$'),
    handler: modules.board.handleB44,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/breakers/'),
    handler: modules.board.handleB45,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/watchlist$'),
    handler: modules.board.handleB46,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/watchlist/'),
    handler: modules.board.handleB47,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/changes$'),
    handler: modules.board.handleB48,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/prospects$'),
    handler: modules.board.handleB49,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/prospects/import$'),
    handler: modules.board.handleB50,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/prospects/'),
    handler: modules.board.handleB51,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/prospects/'),
    handler: modules.board.handleB52,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/outreach/stats$'),
    handler: modules.board.handleB53,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/sequences/'),
    handler: modules.board.handleB54,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/content$'),
    handler: modules.board.handleB55,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/content/'),
    handler: modules.board.handleB56,
  },
  {
    method: "POST",
    pattern: new RegExp('^/siu\\-tin\\-dei/board/content/'),
    handler: modules.board.handleB57,
  },
  {
    pattern: new RegExp('^/siu\\-tin\\-dei/board/content/'),
    handler: modules.board.handleB58,
  },
];

