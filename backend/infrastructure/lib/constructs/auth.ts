import * as cdk from "aws-cdk-lib";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as cr from "aws-cdk-lib/custom-resources";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as sqs from "aws-cdk-lib/aws-sqs";
import * as path from "node:path";
import { Construct } from "constructs";
import { createPythonLambda } from "./python-lambda";

export interface AuthConstructProps {
  readonly adminWebDomainParameter: cdk.CfnParameter;
  readonly googleClientIdParameter: cdk.CfnParameter;
  /** Google OAuth client secret (`noEcho` CloudFormation parameter). */
  readonly googleClientSecretParameter: cdk.CfnParameter;
  readonly cognitoDomainPrefixParameter: cdk.CfnParameter;
  /**
   * Optional custom Hosted UI hostname (e.g. auth.example.com). When set together
   * with {@link cognitoCustomDomainCertificateArnParameter}, the pool uses a
   * custom domain; otherwise the prefix domain is used.
   */
  readonly cognitoCustomDomainNameParameter: cdk.CfnParameter;
  /** ACM cert ARN in us-east-1 for the Cognito custom domain (required with custom name). */
  readonly cognitoCustomDomainCertificateArnParameter: cdk.CfnParameter;
  readonly adminBootstrapEmailParameter: cdk.CfnParameter;
  readonly adminBootstrapTempPasswordParameter: cdk.CfnParameter;
  /** Comma-separated emails that receive the admin group via Pre Token Generation (federated users). */
  readonly adminFederatedEmailAllowlistParameter: cdk.CfnParameter;
  /** Shared CMK for Lambda env vars + log group encryption (CKV_AWS_173/158). */
  readonly sharedEncryptionKey: kms.IKey;
  /** Shared SQS DLQ for failed async invocations (CKV_AWS_116). */
  readonly sharedDeadLetterQueue: sqs.IQueue;
}

/**
 * Cognito user pool with Google federation, TOTP-only MFA, hosted UI OAuth,
 * admin group, Pre Token Generation allow-list for federated admins, and
 * chained custom resources that bootstrap the first native admin user.
 */
export class AuthConstruct extends Construct {
  public readonly userPool: cognito.UserPool;
  public readonly userPoolClient: cognito.UserPoolClient;
  /**
   * Effective origin for Cognito OAuth endpoints (`https://...`), either the
   * prefix domain or the custom domain.
   */
  public readonly cognitoOAuthBaseUrl: string;
  /** True when a custom Hosted UI domain + certificate are configured. */
  public readonly useCustomAuthDomain: cdk.CfnCondition;
  /** L1 domain resource for custom Hosted UI; only created when {@link useCustomAuthDomain} applies. */
  public readonly cognitoCustomHostedDomain: cognito.CfnUserPoolDomain;
  public readonly adminGroup: cognito.CfnUserPoolGroup;
  public readonly adminGroupName = "admin";

  constructor(scope: Construct, id: string, props: AuthConstructProps) {
    super(scope, id);

    const callbackUrl = cdk.Fn.join("", [
      "https://",
      props.adminWebDomainParameter.valueAsString,
      "/auth/callback",
    ]);
    const logoutUrl = cdk.Fn.join("", [
      "https://",
      props.adminWebDomainParameter.valueAsString,
      "/",
    ]);

    this.userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "lxsoftware-admin-user-pool",
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: { email: { required: true, mutable: true } },
      mfa: cognito.Mfa.REQUIRED,
      mfaSecondFactor: { sms: false, otp: true },
      passwordPolicy: {
        minLength: 14,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      standardThreatProtectionMode:
        cognito.StandardThreatProtectionMode.NO_ENFORCEMENT,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const preTokenFn = createPythonLambda(this, "PreTokenGenerationFn", {
      entryDir: path.join(
        __dirname,
        "..",
        "..",
        "..",
        "lambda",
        "pre_token_generation"
      ),
      environmentEncryptionKey: props.sharedEncryptionKey,
      logEncryptionKey: props.sharedEncryptionKey,
      deadLetterQueue: props.sharedDeadLetterQueue,
      environment: {
        ADMIN_EMAIL_ALLOWLIST:
          props.adminFederatedEmailAllowlistParameter.valueAsString,
      },
    });
    props.sharedDeadLetterQueue.grantSendMessages(preTokenFn);

    this.userPool.addTrigger(
      cognito.UserPoolOperation.PRE_TOKEN_GENERATION,
      preTokenFn
    );

    const googleProvider = new cognito.UserPoolIdentityProviderGoogle(
      this,
      "GoogleProvider",
      {
        userPool: this.userPool,
        clientId: props.googleClientIdParameter.valueAsString,
        clientSecretValue: cdk.SecretValue.cfnParameter(
          props.googleClientSecretParameter
        ),
        scopes: ["profile", "email", "openid"],
        attributeMapping: {
          email: cognito.ProviderAttribute.GOOGLE_EMAIL,
          givenName: cognito.ProviderAttribute.GOOGLE_GIVEN_NAME,
          familyName: cognito.ProviderAttribute.GOOGLE_FAMILY_NAME,
          profilePicture: cognito.ProviderAttribute.GOOGLE_PICTURE,
        },
      }
    );

    this.userPoolClient = this.userPool.addClient("UserPoolClient", {
      userPoolClientName: "lxsoftware-admin-spa-client",
      generateSecret: false,
      authFlows: {
        userSrp: true,
        userPassword: true,
        adminUserPassword: true,
        custom: false,
      },
      oAuth: {
        flows: { authorizationCodeGrant: true, implicitCodeGrant: false },
        scopes: [
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.PROFILE,
        ],
        callbackUrls: [callbackUrl],
        logoutUrls: [logoutUrl],
      },
      supportedIdentityProviders: [
        cognito.UserPoolClientIdentityProvider.COGNITO,
        cognito.UserPoolClientIdentityProvider.custom(
          googleProvider.providerName
        ),
      ],
      preventUserExistenceErrors: true,
      enableTokenRevocation: true,
    });

    this.userPoolClient.node.addDependency(googleProvider);

    const useCustomDomain = new cdk.CfnCondition(this, "UseCustomAuthDomain", {
      expression: cdk.Fn.conditionAnd(
        cdk.Fn.conditionNot(
          cdk.Fn.conditionEquals(
            props.cognitoCustomDomainNameParameter.valueAsString,
            ""
          )
        ),
        cdk.Fn.conditionNot(
          cdk.Fn.conditionEquals(
            props.cognitoCustomDomainCertificateArnParameter.valueAsString,
            ""
          )
        )
      ),
    });

    const useCognitoPrefixDomain = new cdk.CfnCondition(
      this,
      "UseCognitoPrefixAuthDomain",
      {
        expression: cdk.Fn.conditionOr(
          cdk.Fn.conditionEquals(
            props.cognitoCustomDomainNameParameter.valueAsString,
            ""
          ),
          cdk.Fn.conditionEquals(
            props.cognitoCustomDomainCertificateArnParameter.valueAsString,
            ""
          )
        ),
      }
    );

    const cognitoPrefixDomain = new cognito.CfnUserPoolDomain(
      this,
      "HostedUIDomainPrefix",
      {
        userPoolId: this.userPool.userPoolId,
        domain: props.cognitoDomainPrefixParameter.valueAsString,
      }
    );
    cognitoPrefixDomain.cfnOptions.condition = useCognitoPrefixDomain;

    const removeCognitoPrefixDomainPolicy =
      cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ["cognito-idp:DeleteUserPoolDomain"],
          resources: [this.userPool.userPoolArn],
        }),
      ]);

    const removeCognitoPrefixDomain = new cr.AwsCustomResource(
      this,
      "RemoveCognitoPrefixAuthDomain",
      {
        onCreate: {
          service: "CognitoIdentityServiceProvider",
          action: "deleteUserPoolDomain",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Domain: props.cognitoDomainPrefixParameter.valueAsString,
          },
          physicalResourceId: cr.PhysicalResourceId.of(
            `remove-cognito-prefix-domain-${this.userPool.userPoolId}`
          ),
          ignoreErrorCodesMatching:
            "ResourceNotFoundException|InvalidParameterException",
        },
        onUpdate: {
          service: "CognitoIdentityServiceProvider",
          action: "deleteUserPoolDomain",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Domain: props.cognitoDomainPrefixParameter.valueAsString,
          },
          physicalResourceId: cr.PhysicalResourceId.of(
            `remove-cognito-prefix-domain-${this.userPool.userPoolId}`
          ),
          ignoreErrorCodesMatching:
            "ResourceNotFoundException|InvalidParameterException",
        },
        policy: removeCognitoPrefixDomainPolicy,
        installLatestAwsSdk: false,
      }
    );
    const removeCognitoPrefixDomainCustomResource = (
      removeCognitoPrefixDomain as unknown as {
        customResource: cdk.CustomResource;
      }
    ).customResource;
    const removeCognitoPrefixDomainResource =
      removeCognitoPrefixDomainCustomResource.node.defaultChild as cdk.CfnResource;
    removeCognitoPrefixDomainResource.cfnOptions.condition = useCustomDomain;

    this.cognitoCustomHostedDomain = new cognito.CfnUserPoolDomain(
      this,
      "HostedUICustomDomain",
      {
        userPoolId: this.userPool.userPoolId,
        domain: props.cognitoCustomDomainNameParameter.valueAsString,
        customDomainConfig: {
          certificateArn:
            props.cognitoCustomDomainCertificateArnParameter.valueAsString,
        },
      }
    );
    this.cognitoCustomHostedDomain.cfnOptions.condition = useCustomDomain;
    this.cognitoCustomHostedDomain.node.addDependency(removeCognitoPrefixDomain);

    const prefixOAuthBaseUrl = cdk.Fn.join("", [
      "https://",
      props.cognitoDomainPrefixParameter.valueAsString,
      ".auth.",
      cdk.Aws.REGION,
      ".amazoncognito.com",
    ]);
    const customOAuthBaseUrl = cdk.Fn.join("", [
      "https://",
      props.cognitoCustomDomainNameParameter.valueAsString,
    ]);
    this.cognitoOAuthBaseUrl = cdk.Fn.conditionIf(
      useCustomDomain.logicalId,
      customOAuthBaseUrl,
      prefixOAuthBaseUrl
    ) as unknown as string;
    this.useCustomAuthDomain = useCustomDomain;

    this.adminGroup = new cognito.CfnUserPoolGroup(this, "AdminGroup", {
      userPoolId: this.userPool.userPoolId,
      groupName: this.adminGroupName,
      description: "Administrators for the LX admin console",
      precedence: 1,
    });

    const bootstrapEmail = props.adminBootstrapEmailParameter.valueAsString;
    const bootstrapPassword =
      props.adminBootstrapTempPasswordParameter.valueAsString;

    const cognitoAdminPolicy = cr.AwsCustomResourcePolicy.fromStatements([
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          "cognito-idp:AdminCreateUser",
          "cognito-idp:AdminSetUserPassword",
          "cognito-idp:AdminAddUserToGroup",
          "cognito-idp:AdminGetUser",
        ],
        resources: [this.userPool.userPoolArn],
      }),
    ]);

    const createBootstrapUser = new cr.AwsCustomResource(
      this,
      "BootstrapAdminCreateUser",
      {
        onCreate: {
          service: "CognitoIdentityServiceProvider",
          action: "adminCreateUser",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: bootstrapEmail,
            MessageAction: "SUPPRESS",
            TemporaryPassword: bootstrapPassword,
            UserAttributes: [
              { Name: "email", Value: bootstrapEmail },
              { Name: "email_verified", Value: "true" },
            ],
          },
          physicalResourceId: cr.PhysicalResourceId.of("lxsoftware-admin-bootstrap-user"),
          ignoreErrorCodesMatching: "UsernameExistsException",
        },
        onUpdate: {
          service: "CognitoIdentityServiceProvider",
          action: "adminGetUser",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: bootstrapEmail,
          },
          physicalResourceId: cr.PhysicalResourceId.of("lxsoftware-admin-bootstrap-user"),
        },
        policy: cognitoAdminPolicy,
        installLatestAwsSdk: false,
      }
    );

    const setBootstrapPassword = new cr.AwsCustomResource(
      this,
      "BootstrapAdminSetPassword",
      {
        onCreate: {
          service: "CognitoIdentityServiceProvider",
          action: "adminSetUserPassword",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: bootstrapEmail,
            Password: bootstrapPassword,
            Permanent: true,
          },
          physicalResourceId: cr.PhysicalResourceId.of("lxsoftware-admin-bootstrap-pw"),
        },
        policy: cognitoAdminPolicy,
        installLatestAwsSdk: false,
      }
    );
    setBootstrapPassword.node.addDependency(createBootstrapUser);

    const addBootstrapToGroup = new cr.AwsCustomResource(
      this,
      "BootstrapAdminAddToGroup",
      {
        onCreate: {
          service: "CognitoIdentityServiceProvider",
          action: "adminAddUserToGroup",
          parameters: {
            UserPoolId: this.userPool.userPoolId,
            Username: bootstrapEmail,
            GroupName: this.adminGroupName,
          },
          physicalResourceId: cr.PhysicalResourceId.of("lxsoftware-admin-bootstrap-group"),
        },
        policy: cognitoAdminPolicy,
        installLatestAwsSdk: false,
      }
    );
    addBootstrapToGroup.node.addDependency(setBootstrapPassword);
    addBootstrapToGroup.node.addDependency(this.adminGroup);
  }
}
