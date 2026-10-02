// aws-cdk-lib runs its built-in "CloudFormation Validate" linter on every
// synth and prints its (advisory-only) report to stderr, which drowns the jest
// output. The same findings are surfaced by `cdk synth`, so keep them there.
process.env.CDK_VALIDATION ??= "false";

/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/test"],
  testMatch: ["**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: "<rootDir>/tsconfig.json" }],
  },
  // Synthesizing the full stack (Cognito, 153 ApiGatewayV2 routes, asset staging) is slow.
  testTimeout: 120_000,
};
