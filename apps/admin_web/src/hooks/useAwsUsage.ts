import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { adminFetch, adminFetchJson } from "../lib/apiAdminClient";
import {
  AWS_USAGE_PATH,
  AWS_USAGE_PDF_PATH,
  type AwsBillingPayload,
} from "../lib/awsBilling";
import { keys } from "../lib/queryKeys";
import { usageRangeQuery } from "../lib/usageMonth";

export function downloadAwsUsagePdfMutationOptions() {
  return {
    mutationFn: async ({ from, to }: { readonly from: string; readonly to: string }) => {
      const res = await adminFetch(`${AWS_USAGE_PDF_PATH}${usageRangeQuery(from, to)}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `lx-software-aws-${from.slice(0, 7)}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },
  };
}

export function useAwsUsage(fromDay: string, toDay: string) {
  return useQuery({
    queryKey: [...keys.admin, "aws-usage", fromDay, toDay],
    queryFn: () =>
      adminFetchJson<AwsBillingPayload>(
        `${AWS_USAGE_PATH}${usageRangeQuery(fromDay, toDay)}`,
      ),
    placeholderData: keepPreviousData,
  });
}
