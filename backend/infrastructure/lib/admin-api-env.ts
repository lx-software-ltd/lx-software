/**
 * Environment variables for AdminApiFn. Each key is assigned once.
 * BOARD_STAFF_ENABLED, BOARD_TOOLS_ENABLED, BOARD_MAIL_SENDING_ENABLED,
 * OUTREACH_SENDING_DOMAIN, and OUTREACH_FROM_LOCAL_PART used to be set again
 * later with the same parameter tokens; the later assignment won, and that
 * single value is what this object sets.
 *
 * BOARD_MAIL_DOMAIN, BOARD_MAIL_RAW_SEGMENT, BOARD_MAIL_INBOUND_ADDRESS,
 * statement-parse notify fields, and PUBLIC_API_BASE_URL are added with
 * addEnvironment after the resources they depend on exist.
 */
export interface AdminApiEnvInput {
  readonly recordsTableName: string;
  readonly auditLogTableName: string;
  readonly assetsBucketName: string;
  readonly assetMaxBytes: string;
  readonly openrouterApiKeySecretArn: string;
  readonly openrouterModel: string;
  readonly openrouterPdfEngine: string;
  readonly openrouterTimeoutSeconds: string;
  readonly parseJobStaleSeconds: string;
  readonly parseJobStuckSeconds: string;
  readonly parseJobTtlSeconds: string;
  readonly enableBankingAppId: string;
  readonly enableBankingKmsKeyId: string;
  readonly githubReadTokenSecretArn: string;
  readonly boardGithubRepo: string;
  readonly boardChatModel: string;
  readonly boardMeetingModel: string;
  readonly boardDeepDiveModel: string;
  readonly boardToolsEnabled: string;
  readonly boardStaffEnabled: string;
  readonly boardCatalogImportEnabled: string;
  readonly siutindeiAdminApiBaseUrl: string;
  readonly siutindeiUserPoolId: string;
  readonly boardImporterClientId: string;
  readonly boardCatalogManagerId: string;
  readonly boardImporterCredentialsSecretArn: string;
  readonly publicApiWritesEnabled: string;
  readonly outreachSendingDomain: string;
  readonly outreachFromLocalPart: string;
  readonly newsletterConfigSet: string;
  readonly newsletterFromLocalPart: string;
  readonly searchApiKeySecretArn: string;
  readonly boardAwsStackPrefix: string;
  readonly boardAwsLambdaNames: string;
  readonly userPoolId: string;
  readonly siutindeiClusterArn: string;
  readonly siutindeiDbSecretArn: string;
  readonly evolvesproutsClusterArn: string;
  readonly evolvesproutsDbSecretArn: string;
  readonly evolvesproutsDbName: string;
  readonly metaBoardTokenSecretArn: string;
  readonly metaAppSecretSecretArn: string;
  readonly metaVerifyToken: string;
  readonly metaPageId: string;
  readonly metaIgUserId: string;
  readonly metaWaPhoneNumberId: string;
  readonly metaWabaId: string;
  readonly metaAdAccountId: string;
  readonly appStoreConnectKeySecretArn: string;
  readonly googlePlayServiceAccountSecretArn: string;
  readonly appStoreConnectAppId: string;
  readonly ascVendorNumber: string;
  readonly googlePlayPackageName: string;
  readonly googleAnalyticsServiceAccountSecretArn: string;
  readonly googlePlacesKeySecretArn: string;
  readonly boardLinkSigningSecretArn: string;
  readonly ga4PropertyIds: string;
  readonly gtmContainers: string;
  readonly boardMailSendingEnabled: string;
  readonly adminWebOrigin: string;
}

export function buildAdminEnv(input: AdminApiEnvInput): Record<string, string> {
  const env: Record<string, string> = {
    RECORDS_TABLE_NAME: input.recordsTableName,
    AUDIT_LOG_TABLE_NAME: input.auditLogTableName,
    ASSETS_BUCKET_NAME: input.assetsBucketName,
    ASSET_MAX_BYTES: input.assetMaxBytes,
    OPENROUTER_API_KEY_SECRET_ARN: input.openrouterApiKeySecretArn,
    OPENROUTER_MODEL: input.openrouterModel,
    OPENROUTER_PDF_ENGINE: input.openrouterPdfEngine,
    OPENROUTER_TIMEOUT_SECONDS: input.openrouterTimeoutSeconds,
    PARSE_JOB_STALE_SECONDS: input.parseJobStaleSeconds,
    PARSE_JOB_STUCK_SECONDS: input.parseJobStuckSeconds,
    PARSE_JOB_TTL_SECONDS: input.parseJobTtlSeconds,
    ENABLE_BANKING_APP_ID: input.enableBankingAppId,
    ENABLE_BANKING_KMS_KEY_ID: input.enableBankingKmsKeyId,
    GITHUB_READ_TOKEN_SECRET_ARN: input.githubReadTokenSecretArn,
    BOARD_GITHUB_REPO: input.boardGithubRepo,
    BOARD_CHAT_MODEL: input.boardChatModel,
    BOARD_MEETING_MODEL: input.boardMeetingModel,
    BOARD_DEEP_DIVE_MODEL: input.boardDeepDiveModel,
    BOARD_TOOLS_ENABLED: input.boardToolsEnabled,
    BOARD_STAFF_ENABLED: input.boardStaffEnabled,
    BOARD_CATALOG_IMPORT_ENABLED: input.boardCatalogImportEnabled,
    SIUTINDEI_ADMIN_API_BASE_URL: input.siutindeiAdminApiBaseUrl,
    SIUTINDEI_USER_POOL_ID: input.siutindeiUserPoolId,
    BOARD_IMPORTER_CLIENT_ID: input.boardImporterClientId,
    BOARD_CATALOG_MANAGER_ID: input.boardCatalogManagerId,
    BOARD_IMPORTER_CREDENTIALS_SECRET_ARN: input.boardImporterCredentialsSecretArn,
    PUBLIC_API_WRITES_ENABLED: input.publicApiWritesEnabled,
    OUTREACH_SENDING_DOMAIN: input.outreachSendingDomain,
    OUTREACH_FROM_LOCAL_PART: input.outreachFromLocalPart,
    NEWSLETTER_CONFIG_SET: input.newsletterConfigSet,
    NEWSLETTER_FROM_LOCAL_PART: input.newsletterFromLocalPart,
    SEARCH_API_KEY_SECRET_ARN: input.searchApiKeySecretArn,
    BOARD_AWS_STACK_PREFIX: input.boardAwsStackPrefix,
    BOARD_AWS_LAMBDA_NAMES: input.boardAwsLambdaNames,
    USER_POOL_ID: input.userPoolId,
    SIUTINDEI_CLUSTER_ARN: input.siutindeiClusterArn,
    SIUTINDEI_DB_SECRET_ARN: input.siutindeiDbSecretArn,
    EVOLVESPROUTS_CLUSTER_ARN: input.evolvesproutsClusterArn,
    EVOLVESPROUTS_DB_SECRET_ARN: input.evolvesproutsDbSecretArn,
    EVOLVESPROUTS_DB_NAME: input.evolvesproutsDbName,
    META_BOARD_TOKEN_SECRET_ARN: input.metaBoardTokenSecretArn,
    META_APP_SECRET_SECRET_ARN: input.metaAppSecretSecretArn,
    META_VERIFY_TOKEN: input.metaVerifyToken,
    META_PAGE_ID: input.metaPageId,
    META_IG_USER_ID: input.metaIgUserId,
    META_WA_PHONE_NUMBER_ID: input.metaWaPhoneNumberId,
    META_WABA_ID: input.metaWabaId,
    META_AD_ACCOUNT_ID: input.metaAdAccountId,
    APP_STORE_CONNECT_KEY_SECRET_ARN: input.appStoreConnectKeySecretArn,
    GOOGLE_PLAY_SERVICE_ACCOUNT_SECRET_ARN: input.googlePlayServiceAccountSecretArn,
    APP_STORE_CONNECT_APP_ID: input.appStoreConnectAppId,
    ASC_VENDOR_NUMBER: input.ascVendorNumber,
    GOOGLE_PLAY_PACKAGE_NAME: input.googlePlayPackageName,
    GOOGLE_ANALYTICS_SERVICE_ACCOUNT_SECRET_ARN: input.googleAnalyticsServiceAccountSecretArn,
    GOOGLE_PLACES_KEY_SECRET_ARN: input.googlePlacesKeySecretArn,
    BOARD_LINK_SIGNING_SECRET_ARN: input.boardLinkSigningSecretArn,
    GA4_PROPERTY_IDS: input.ga4PropertyIds,
    GTM_CONTAINERS: input.gtmContainers,
    BOARD_MAIL_SENDING_ENABLED: input.boardMailSendingEnabled,
    ADMIN_WEB_ORIGIN: input.adminWebOrigin,
  };
  const keys = Object.keys(env);
  if (new Set(keys).size !== keys.length) {
    throw new Error("AdminApiFn environment keys are not unique");
  }
  return env;
}
