from prowler.lib.check.models import Check, Check_Report_AWS
from prowler.providers.aws.services.autoscaling.autoscaling_client import (
    autoscaling_client,
)


class autoscaling_group_multiple_az(Check):
    def execute(self):
        findings = []
        for group in autoscaling_client.groups:
            report = Check_Report_AWS(metadata=self.metadata(), resource=group)

            report.status = "FAIL"
            report.status_extended = (
                f"Autoscaling group {group.name} has only one availability zones."
            )
            if len(group.availability_zones) > 1:
                report.status = "PASS"
                report.status_extended = (
                    f"Autoscaling group {group.name} has multiple availability zones."
                )

            findings.append(report)

        return findings
