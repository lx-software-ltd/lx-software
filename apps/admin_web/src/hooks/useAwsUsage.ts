import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  AWS_USAGE_PATH,
  type AwsBillingPayload,
} from "../lib/awsBilling";
import { usageRangeQuery } from "../lib/usageMonth";

export function useAwsUsage(fromDay: string, toDay: string) {
  return useQuery({
    queryKey: ["admin", "aws-usage", fromDay, toDay],
    queryFn: () =>
      adminFetchJson<AwsBillingPayload>(
        `${AWS_USAGE_PATH}${usageRangeQuery(fromDay, toDay)}`,
      ),
    placeholderData: keepPreviousData,
  });
}
