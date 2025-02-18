from prowler.lib.check.models import Check, Check_Report_Azure
from prowler.providers.azure.services.entra.entra_client import entra_client
from prowler.providers.azure.services.entra.lib.user_privileges import (
    is_privileged_user,
)


class entra_non_privileged_user_has_mfa(Check):
    def execute(self) -> Check_Report_Azure:
        findings = []

        for tenant_domain, users in entra_client.users.items():
            for user in users.values():
                if not is_privileged_user(
                    user, entra_client.directory_roles[tenant_domain]
                ):
                    report = Check_Report_Azure(metadata=self.metadata(), resource=user)
                    report.subscription = f"Tenant: {tenant_domain}"
                    report.status = "FAIL"
                    report.status_extended = (
                        f"Non-privileged user {user.name} does not have MFA."
                    )

                    if len(user.authentication_methods) > 1:
                        report.status = "PASS"
                        report.status_extended = (
                            f"Non-privileged user {user.name} has MFA."
                        )

                    findings.append(report)

        return findings
