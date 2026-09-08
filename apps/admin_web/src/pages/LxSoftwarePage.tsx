import { OpenRouterUsageCard } from "../components/dashboard/OpenRouterUsageCard";
import { AwsUsageCard } from "../components/dashboard/AwsUsageCard";
import { useOpenRouterUsage } from "../hooks/useOpenRouterUsage";
import { useAwsUsage } from "../hooks/useAwsUsage";
import { LX_SOFTWARE_BOOK_KEY } from "../lib/statementOwners";
import { StatementBookPage } from "./StatementBookPage";

export function LxSoftwarePage() {
  const openrouterQuery = useOpenRouterUsage();
  const awsQuery = useAwsUsage();
  return (
    <StatementBookPage
      bookKey={LX_SOFTWARE_BOOK_KEY}
      dashboardExtra={
        <div className="d-flex flex-column gap-3">
          <AwsUsageCard
            isLoading={awsQuery.isLoading}
            isError={awsQuery.isError}
            data={awsQuery.data}
          />
          <OpenRouterUsageCard
            isLoading={openrouterQuery.isLoading}
            isError={openrouterQuery.isError}
            data={openrouterQuery.data}
          />
        </div>
      }
    />
  );
}
