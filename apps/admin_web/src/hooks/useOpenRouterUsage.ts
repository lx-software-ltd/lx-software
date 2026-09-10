import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  OPENROUTER_USAGE_PATH,
  type OpenRouterUsagePayload,
} from "../lib/openrouterUsage";
import { usageRangeQuery } from "../lib/usageMonth";

export function useOpenRouterUsage(fromDay: string, toDay: string) {
  return useQuery({
    queryKey: ["admin", "openrouter-usage", fromDay, toDay],
    queryFn: () =>
      adminFetchJson<OpenRouterUsagePayload>(
        `${OPENROUTER_USAGE_PATH}${usageRangeQuery(fromDay, toDay)}`,
      ),
    placeholderData: keepPreviousData,
  });
}
