import { OpenRouterUsageCard } from "../components/dashboard/OpenRouterUsageCard";
import { useOpenRouterUsage } from "../hooks/useOpenRouterUsage";
import { LX_SOFTWARE_BOOK_KEY } from "../lib/statementOwners";
import { StatementBookPage } from "./StatementBookPage";

export function LxSoftwarePage() {
  const openrouterQuery = useOpenRouterUsage();
  return (
    <StatementBookPage
      bookKey={LX_SOFTWARE_BOOK_KEY}
      dashboardExtra={
        <OpenRouterUsageCard
          isLoading={openrouterQuery.isLoading}
          isError={openrouterQuery.isError}
          data={openrouterQuery.data}
        />
      }
    />
  );
}
