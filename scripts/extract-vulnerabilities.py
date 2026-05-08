#!/usr/bin/env python3

"""
Strix Vulnerability Extraction Script

Extract and format vulnerability findings from a Strix scan run.
Supports multiple output formats: summary, detailed, JSON, CSV.

If no run directory is provided, defaults to the most recently modified
subdirectory of strix_runs/.

Usage:
    python3 extract-vulnerabilities.py [run_directory] [--format FORMAT] [--output FILE]

Examples:
    python3 extract-vulnerabilities.py
    python3 extract-vulnerabilities.py strix_runs/grow-441e-75040-beta-clio-dev_1695
    python3 extract-vulnerabilities.py strix_runs/my-scan --format json --output findings.json
    python3 extract-vulnerabilities.py strix_runs/my-scan --format detailed
    python3 extract-vulnerabilities.py strix_runs/my-scan --format csv --output report.csv
"""

import json
import csv
import sys
import argparse
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


def load_vulnerabilities_csv(run_dir: Path) -> List[Dict[str, Any]]:
    """Load vulnerability summary from CSV file."""
    csv_file = run_dir / "vulnerabilities.csv"
    if not csv_file.exists():
        return []

    vulnerabilities = []
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            vulnerabilities.append(row)

    return vulnerabilities


def load_vulnerability_details(run_dir: Path, vuln_id: str) -> Optional[Dict[str, Any]]:
    """Load detailed vulnerability information from markdown file."""
    md_file = run_dir / "vulnerabilities" / f"{vuln_id}.md"
    if not md_file.exists():
        return None

    with open(md_file, 'r') as f:
        content = f.read()

    # Parse metadata from the markdown file
    details = {"raw_content": content}

    # Extract title (first line starting with #)
    title_match = re.search(r'^# (.+)$', content, re.MULTILINE)
    if title_match:
        details["title"] = title_match.group(1).strip()

    # Extract metadata section
    metadata_patterns = [
        (r'\*\*ID:\*\* (.+)', 'id'),
        (r'\*\*Severity:\*\* (.+)', 'severity'),
        (r'\*\*Found:\*\* (.+)', 'timestamp'),
        (r'\*\*Target:\*\* (.+)', 'target'),
        (r'\*\*Endpoint:\*\* (.+)', 'endpoint'),
        (r'\*\*Method:\*\* (.+)', 'method'),
        (r'\*\*CWE:\*\* (.+)', 'cwe'),
        (r'\*\*CVSS:\*\* (.+)', 'cvss'),
    ]

    for pattern, field in metadata_patterns:
        match = re.search(pattern, content)
        if match:
            details[field] = match.group(1).strip()

    # Extract major sections
    sections = {
        'description': r'## Description\s*\n\n(.*?)(?=\n## |\Z)',
        'impact': r'## Impact\s*\n\n(.*?)(?=\n## |\Z)',
        'technical_analysis': r'## Technical Analysis\s*\n\n(.*?)(?=\n## |\Z)',
        'proof_of_concept': r'## Proof of Concept\s*\n\n(.*?)(?=\n## |\Z)',
        'remediation': r'## Remediation\s*\n\n(.*?)(?=\n## |\Z)',
        'references': r'## References\s*\n\n(.*?)(?=\n## |\Z)',
    }

    for section_name, pattern in sections.items():
        match = re.search(pattern, content, re.DOTALL)
        if match:
            details[section_name] = match.group(1).strip()

    return details


def format_summary_output(vulnerabilities: List[Dict[str, Any]]) -> str:
    """Format vulnerabilities as a summary table."""
    if not vulnerabilities:
        return "✅ No vulnerabilities found!"

    output = []
    output.append("🔍 VULNERABILITY SUMMARY")
    output.append("=" * 80)
    output.append("")

    # Group by severity
    severity_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
    by_severity = {}
    for vuln in vulnerabilities:
        severity = vuln.get('severity', 'UNKNOWN').upper()
        if severity not in by_severity:
            by_severity[severity] = []
        by_severity[severity].append(vuln)

    # Summary stats
    total = len(vulnerabilities)
    severity_counts = {sev: len(by_severity.get(sev, [])) for sev in severity_order}

    output.append(f"📊 Total findings: {total}")
    for severity in severity_order:
        count = severity_counts[severity]
        if count > 0:
            emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(severity, "⚫")
            output.append(f"   {emoji} {severity}: {count}")
    output.append("")

    # Detailed listing by severity
    for severity in severity_order:
        vulns = by_severity.get(severity, [])
        if not vulns:
            continue

        emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}.get(severity, "⚫")
        output.append(f"{emoji} {severity} SEVERITY ({len(vulns)})")
        output.append("-" * 40)

        for vuln in vulns:
            output.append(f"  • {vuln.get('title', 'Unknown Title')} ({vuln.get('id', 'no-id')})")
            if vuln.get('timestamp'):
                output.append(f"    Found: {vuln['timestamp']}")
            output.append("")

    return "\n".join(output)


def format_detailed_output(run_dir: Path, vulnerabilities: List[Dict[str, Any]], truncate_sections: bool = False) -> str:
    """Format vulnerabilities with full details."""
    if not vulnerabilities:
        return "✅ No vulnerabilities found!"

    output = []
    output.append("🔍 DETAILED VULNERABILITY REPORT")
    output.append("=" * 80)
    output.append("")

    for i, vuln in enumerate(vulnerabilities, 1):
        vuln_id = vuln.get('id', 'unknown')
        details = load_vulnerability_details(run_dir, vuln_id)

        output.append(f"🚨 VULNERABILITY {i}/{len(vulnerabilities)}")
        output.append("-" * 80)
        output.append("")

        # Basic info
        output.append(f"📋 ID: {vuln_id}")
        output.append(f"📝 Title: {vuln.get('title', 'Unknown')}")
        output.append(f"🚨 Severity: {vuln.get('severity', 'Unknown')}")
        output.append(f"🕒 Found: {vuln.get('timestamp', 'Unknown')}")

        if details:
            if details.get('cvss'):
                output.append(f"📊 CVSS Score: {details['cvss']}")
            if details.get('cwe'):
                output.append(f"🔗 CWE: {details['cwe']}")
            if details.get('target'):
                output.append(f"🎯 Target: {details['target']}")
            if details.get('endpoint'):
                output.append(f"🔗 Endpoint: {details['endpoint']}")

        output.append("")

        # Main sections
        if details:
            for section_name, section_title in [
                ('description', '📄 Description'),
                ('impact', '💥 Impact'),
                ('technical_analysis', '🔬 Technical Analysis'),
            ]:
                section_content = details.get(section_name)
                if section_content:
                    output.append(f"{section_title}:")
                    # Truncate very long sections only if requested
                    if truncate_sections and len(section_content) > 1000:
                        section_content = section_content[:1000] + "\n\n[... truncated for brevity ...]"
                    output.append(section_content)
                    output.append("")

        output.append("=" * 80)
        output.append("")

    return "\n".join(output)


def format_json_output(run_dir: Path, vulnerabilities: List[Dict[str, Any]]) -> str:
    """Format vulnerabilities as JSON."""
    detailed_vulns = []

    for vuln in vulnerabilities:
        vuln_data = dict(vuln)  # Copy CSV data

        # Load detailed information
        vuln_id = vuln.get('id')
        if vuln_id:
            details = load_vulnerability_details(run_dir, vuln_id)
            if details:
                # Remove raw content to keep JSON clean
                details.pop('raw_content', None)
                vuln_data.update(details)

        detailed_vulns.append(vuln_data)

    return json.dumps({
        "scan_summary": {
            "total_vulnerabilities": len(vulnerabilities),
            "severity_breakdown": _get_severity_breakdown(vulnerabilities),
            "extracted_at": datetime.now().isoformat(),
        },
        "vulnerabilities": detailed_vulns
    }, indent=2)


def format_csv_output(run_dir: Path, vulnerabilities: List[Dict[str, Any]]) -> str:
    """Format vulnerabilities as enhanced CSV."""
    if not vulnerabilities:
        return "id,title,severity,timestamp\n"

    # Collect all possible fields
    all_fields = set()
    enhanced_vulns = []

    for vuln in vulnerabilities:
        enhanced_vuln = dict(vuln)

        # Load detailed information
        vuln_id = vuln.get('id')
        if vuln_id:
            details = load_vulnerability_details(run_dir, vuln_id)
            if details:
                # Add key fields from detailed analysis
                for field in ['cvss', 'cwe', 'target', 'endpoint', 'method']:
                    if field in details:
                        enhanced_vuln[field] = details[field]

                # Add first paragraph of description
                if details.get('description'):
                    desc = details['description'].split('\n\n')[0]
                    enhanced_vuln['description_summary'] = desc[:200] + "..." if len(desc) > 200 else desc

        enhanced_vulns.append(enhanced_vuln)
        all_fields.update(enhanced_vuln.keys())

    # Create CSV output
    from io import StringIO
    output = StringIO()

    # Define field order
    ordered_fields = ['id', 'title', 'severity', 'cvss', 'timestamp', 'target', 'endpoint', 'method', 'cwe', 'description_summary']
    remaining_fields = sorted([f for f in all_fields if f not in ordered_fields])
    final_fields = [f for f in ordered_fields if f in all_fields] + remaining_fields

    writer = csv.DictWriter(output, fieldnames=final_fields)
    writer.writeheader()
    for vuln in enhanced_vulns:
        writer.writerow(vuln)

    return output.getvalue()


def _get_severity_breakdown(vulnerabilities: List[Dict[str, Any]]) -> Dict[str, int]:
    """Get count of vulnerabilities by severity."""
    breakdown = {}
    for vuln in vulnerabilities:
        severity = vuln.get('severity', 'Unknown').upper()
        breakdown[severity] = breakdown.get(severity, 0) + 1
    return breakdown


def find_latest_run_dir(base: Path = Path("strix_runs")) -> Optional[Path]:
    """Return the most recently modified subdirectory of strix_runs/, or None."""
    if not base.is_dir():
        return None
    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def main():
    parser = argparse.ArgumentParser(description="Extract vulnerability findings from Strix scan")
    parser.add_argument("run_dir", nargs="?", default=None,
                       help="Path to the Strix run directory (default: most recent in strix_runs/)")
    parser.add_argument("--format", "-f", choices=['summary', 'detailed', 'json', 'csv'],
                       default='summary', help="Output format (default: summary)")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    parser.add_argument("--quiet", "-q", action="store_true",
                       help="Suppress progress messages")
    parser.add_argument("--truncate", action="store_true",
                       help="Truncate long sections in detailed format for readability")

    args = parser.parse_args()

    if args.run_dir is None:
        run_dir = find_latest_run_dir()
        if run_dir is None:
            print("❌ No run directories found in strix_runs/", file=sys.stderr)
            sys.exit(1)
        if not args.quiet:
            print(f"📁 Using most recent run: {run_dir}", file=sys.stderr)
    else:
        run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"❌ Run directory does not exist: {run_dir}", file=sys.stderr)
        sys.exit(1)

    try:
        # Load vulnerabilities
        if not args.quiet:
            print("📖 Loading vulnerability data...", file=sys.stderr)

        vulnerabilities = load_vulnerabilities_csv(run_dir)

        if not args.quiet:
            print(f"✅ Found {len(vulnerabilities)} vulnerabilities", file=sys.stderr)

        # Format output
        if args.format == 'summary':
            output_text = format_summary_output(vulnerabilities)
        elif args.format == 'detailed':
            output_text = format_detailed_output(run_dir, vulnerabilities, args.truncate)
        elif args.format == 'json':
            output_text = format_json_output(run_dir, vulnerabilities)
        elif args.format == 'csv':
            output_text = format_csv_output(run_dir, vulnerabilities)
        else:
            raise ValueError(f"Unknown format: {args.format}")

        # Write output
        if args.output:
            output_file = Path(args.output)
            with open(output_file, 'w') as f:
                f.write(output_text)
            if not args.quiet:
                print(f"📝 Output written to: {output_file}", file=sys.stderr)
        else:
            print(output_text)

    except Exception as e:
        print(f"❌ Error extracting vulnerabilities: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()