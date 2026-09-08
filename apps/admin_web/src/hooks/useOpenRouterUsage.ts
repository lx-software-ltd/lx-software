import { useQuery } from "@tanstack/react-query";
import { adminFetchJson } from "../lib/apiAdminClient";
import {
  OPENROUTER_USAGE_PATH,
  type OpenRouterUsagePayload,
} from "../lib/openrouterUsage";

export function useOpenRouterUsage() {
  return useQuery({
    queryKey: ["admin", "openrouter-usage"],
    queryFn: () => adminFetchJson<OpenRouterUsagePayload>(OPENROUTER_USAGE_PATH),
  });
}
