import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as schedulerTargets from "aws-cdk-lib/aws-scheduler-targets";

/**
 * EventBridge Scheduler targets for AdminApiFn. Each schedule is a direct
 * child of the stack (same construct ids as before).
 */
export function defineBoardSchedules(
  scope: cdk.Stack,
  adminFn: lambda.IFunction,
  hasEvolvesproutsDataApi: cdk.CfnCondition,
) {
  // Siu Tin Dei Executive Board schedules. Explicit scheduleName + boardKey
  // so a later LX Software board can add a parallel set without colliding.
  // EventBridge Scheduler (not an events.Rule): invokes through an IAM role
  // so we do not add more Lambda resource-policy statements (20 KB cap).
  const siutindeiBoardKey = "siuTinDei";
  const siutindeiBoardSchedule = (
    id: string,
    scheduleName: string,
    description: string,
    schedule: scheduler.ScheduleExpression,
    input: Record<string, string>,
    retryAttempts: number
  ) =>
    new scheduler.Schedule(scope, id, {
      scheduleName,
      description,
      schedule,
      target: new schedulerTargets.LambdaInvoke(adminFn, {
        input: scheduler.ScheduleTargetInput.fromObject({
          ...input,
          boardKey: siutindeiBoardKey,
        }),
        retryAttempts,
      }),
    });
  const siutindeiStandup = (id: string, name: string, slot: "morning" | "evening", hour: string) =>
    siutindeiBoardSchedule(
      id,
      name,
      `Siu Tin Dei Executive Board ${slot} stand-up (${hour.padStart(2, "0")}:00 HKT) when enabled in settings.`,
      scheduler.ScheduleExpression.cron({
        minute: "0",
        hour,
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      { internal: "board_meeting", trigger: "schedule", slot },
      0
    );
  siutindeiStandup(
    "SiutindeiBoardMorningMeetingSchedule",
    "lxsoftware-admin-siutindei-board-standup-morning",
    "morning",
    "6"
  );
  siutindeiStandup(
    "SiutindeiBoardEveningMeetingSchedule",
    "lxsoftware-admin-siutindei-board-standup-evening",
    "evening",
    "18"
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardReceivablesMirrorSchedule",
    "lxsoftware-admin-siutindei-board-receivables-mirror",
    "Nightly mirror of siutindei invoices/payments into the Siu Tin Dei statement book (HKT 00:30).",
    scheduler.ScheduleExpression.cron({
      minute: "30",
      hour: "0",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_receivables_mirror" },
    1
  );
  const evolvesproutsFinanceMirror = new scheduler.Schedule(
    scope,
    "EvolvesproutsFinanceMirrorSchedule",
    {
      scheduleName: "lxsoftware-admin-evolvesprouts-finance-mirror",
      description:
        "Nightly mirror of Evolve Sprouts payments, refunds and submitted expenses into the Evolve Sprouts statement book (HKT 00:45).",
      schedule: scheduler.ScheduleExpression.cron({
        minute: "45",
        hour: "0",
        timeZone: cdk.TimeZone.ASIA_HONG_KONG,
      }),
      target: new schedulerTargets.LambdaInvoke(adminFn, {
        input: scheduler.ScheduleTargetInput.fromObject({
          internal: "evolvesprouts_finance_mirror",
        }),
        retryAttempts: 1,
      }),
    }
  );
  (evolvesproutsFinanceMirror.node.defaultChild as cdk.CfnResource).cfnOptions.condition =
    hasEvolvesproutsDataApi;
  siutindeiBoardSchedule(
    "SiutindeiBoardDunningSchedule",
    "lxsoftware-admin-siutindei-board-dunning",
    "Daily 09:00 HKT dunning: queues propose-level invoice reminders at D+7 / D+21 / D+35.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "9",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_dunning" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardCacheRefreshSchedule",
    "lxsoftware-admin-siutindei-board-cache-refresh",
    "Hourly refresh of Siu Tin Dei Executive Board AWS / security / stores / web cache (HKT).",
    scheduler.ScheduleExpression.rate(cdk.Duration.hours(1)),
    { internal: "board_cache_refresh" },
    1
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardStaffTickSchedule",
    "lxsoftware-admin-siutindei-board-staff-tick",
    "Every 5 minutes: drain the staff task queue and sweep stuck tasks.",
    scheduler.ScheduleExpression.rate(cdk.Duration.minutes(5)),
    { internal: "board_staff_tick" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardReviewCompileSchedule",
    "lxsoftware-admin-siutindei-board-review-compile",
    "Daily 07:15 HKT compile of the Executive Board review snapshot.",
    scheduler.ScheduleExpression.cron({
      minute: "15",
      hour: "7",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_review_compile" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardReviewSendSchedule",
    "lxsoftware-admin-siutindei-board-review-send",
    "Daily 07:30 HKT digest email of the Executive Board review.",
    scheduler.ScheduleExpression.cron({
      minute: "30",
      hour: "7",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_review_send" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardIntelCrawlSchedule",
    "lxsoftware-admin-siutindei-board-intel-crawl",
    "Daily 03:00 HKT crawl of the Executive Board competitor watchlist.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "3",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_intel_crawl" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardCatalogDiscoverySchedule",
    "lxsoftware-admin-siutindei-board-catalog-discovery",
    "Daily 03:30 HKT catalog discovery: Places sweep, weekly open-data refresh, Places-field expiry.",
    scheduler.ScheduleExpression.cron({
      minute: "30",
      hour: "3",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_catalog_discovery" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardIntelWeeklySchedule",
    "lxsoftware-admin-siutindei-board-intel-weekly",
    "Monday 04:00 HKT watchlist discovery and weekly market brief.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "4",
      weekDay: "MON",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_intel_weekly" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardTargetsSchedule",
    "lxsoftware-admin-siutindei-board-targets",
    "Daily 08:00 HKT pipeline target check: qualify shortfall, due touches, cap raise.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "8",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_targets" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardContentPlanSchedule",
    "lxsoftware-admin-siutindei-board-content-plan",
    "Sunday 18:00 HKT content calendar planning duty.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "18",
      weekDay: "SUN",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_content_plan" },
    0
  );
  siutindeiBoardSchedule(
    "SiutindeiBoardContentReadoutSchedule",
    "lxsoftware-admin-siutindei-board-content-readout",
    "Monday 09:00 HKT weekly content performance readout.",
    scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "9",
      weekDay: "MON",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    { internal: "board_content_readout" },
    0
  );
  new scheduler.Schedule(scope, "OpenRouterUsagePullSchedule", {
    scheduleName: "lxsoftware-admin-openrouter-usage-pull",
    description:
      "Hourly pull of sibling OpenRouter key spend (Evolve Sprouts, Siu Tin Dei) into the usage ledger. Requires the management field on the OpenRouter secret.",
    schedule: scheduler.ScheduleExpression.rate(cdk.Duration.hours(1)),
    target: new schedulerTargets.LambdaInvoke(adminFn, {
      input: scheduler.ScheduleTargetInput.fromObject({
        internal: "openrouter_usage_pull",
      }),
      retryAttempts: 1,
    }),
  });

  // Daily unattended balance refresh (05:30 HKT). The handler no-ops when
  // ENABLE_BANKING_APP_ID is blank. Scheduler invokes through an IAM role so
  // AdminApiFn does not gain an events.amazonaws.com resource policy.
  new scheduler.Schedule(scope, "LxSoftwareLinkedinPlanSchedule", {
    scheduleName: "lxsoftware-admin-linkedin-plan",
    description: "Sunday 18:00 HKT LinkedIn draft generation when LxSoftwareLinkedinEnabled is true.",
    schedule: scheduler.ScheduleExpression.cron({
      minute: "0",
      hour: "18",
      weekDay: "SUN",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    target: new schedulerTargets.LambdaInvoke(adminFn, {
      input: scheduler.ScheduleTargetInput.fromObject({
        internal: "linkedin_weekly_plan",
      }),
      retryAttempts: 0,
    }),
  });
  new scheduler.Schedule(scope, "LxSoftwareLinkedinPublishSchedule", {
    scheduleName: "lxsoftware-admin-linkedin-publish",
    description:
      "Every 15 minutes, remind the owner when an approved LinkedIn slot is due. Direct publishing stays off.",
    schedule: scheduler.ScheduleExpression.rate(cdk.Duration.minutes(15)),
    target: new schedulerTargets.LambdaInvoke(adminFn, {
      input: scheduler.ScheduleTargetInput.fromObject({
        internal: "linkedin_publish_due",
      }),
      retryAttempts: 0,
    }),
  });
  new scheduler.Schedule(scope, "BankSyncDailySchedule", {
    scheduleName: "lxsoftware-admin-bank-sync",
    description:
      "Daily Enable Banking balance sync into the finance accounts sheet (05:30 HKT).",
    schedule: scheduler.ScheduleExpression.cron({
      minute: "30",
      hour: "5",
      timeZone: cdk.TimeZone.ASIA_HONG_KONG,
    }),
    target: new schedulerTargets.LambdaInvoke(adminFn, {
      input: scheduler.ScheduleTargetInput.fromObject({
        internal: "bank_sync",
      }),
      // One retry can run the sync twice; balance writes are idempotent.
      retryAttempts: 1,
    }),
  });
}
