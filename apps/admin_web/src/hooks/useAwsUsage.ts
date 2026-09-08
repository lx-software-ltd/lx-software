import { useQuery } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import { AWS_USAGE_PATH, type AwsBillingPayload } from "../lib/awsBilling";

export function useAwsUsage() {
  return useQuery({
    queryKey: ["admin", "aws-usage"],
    queryFn: () => adminFetchJson<AwsBillingPayload>(AWS_USAGE_PATH),
  });
}
