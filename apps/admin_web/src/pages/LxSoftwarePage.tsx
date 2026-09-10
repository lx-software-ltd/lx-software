import { OpenRouterUsageCard } from "../components/dashboard/OpenRouterUsageCard";
import { AwsUsageCard } from "../components/dashboard/AwsUsageCard";
import { LX_SOFTWARE_BOOK_KEY } from "../lib/statementOwners";
import { StatementBookPage } from "./StatementBookPage";

export function LxSoftwarePage() {
  return (
    <StatementBookPage
      bookKey={LX_SOFTWARE_BOOK_KEY}
      dashboardExtra={
        <div className="row g-3">
          <div className="col-12 col-md-6">
            <AwsUsageCard />
          </div>
          <div className="col-12 col-md-6">
            <OpenRouterUsageCard />
          </div>
        </div>
      }
    />
  );
}
