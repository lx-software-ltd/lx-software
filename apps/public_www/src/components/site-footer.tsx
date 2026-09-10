import { NewsletterForm } from "./NewsletterForm";

export function SiteFooter() {
  return (
    <footer className="border-top bg-white mt-auto">
      <div className="container py-4">
        <div className="row g-4 align-items-start">
          <div className="col-12 col-md-6">
            <NewsletterForm />
          </div>
          <div className="col-12 col-md-6 d-flex flex-column gap-2">
            <span className="text-muted">
              © {new Date().getFullYear()} LX Software. All rights reserved.
            </span>
            <span className="text-muted">
              Built with Vite, React Router, TanStack Query, and Bootstrap 5.
            </span>
          </div>
        </div>
      </div>
    </footer>
  );
}
