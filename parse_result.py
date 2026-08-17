#!/usr/bin/env python3
""" 
Parse all .qpa files from a results folder or URL and generate a summary report.
Shows test summary in table format for each .qpa file after analysis.
Supports:
  - Local folder with .qpa files
  - Direct qvsfilestore URL to a .qpa file  (Ex: https://qvsfilestore/builds_mobile/QVSLogs/rel-39/../TestLogs )
  - URL to an HTML page listing .qpa files
"""

import re
import sys
import os
import glob
from collections import defaultdict
from datetime import datetime
import urllib.request
import urllib.parse
from html.parser import HTMLParser
import tempfile
import ssl

# Replace qvsfilestore URL with local mount point so paths are read from disk
QVSFILESTORE_URL_PREFIX = "https://qvsfilestore/"
QVSFILESTORE_MOUNT_POINT = "/mnt/"


def normalize_qpa_url(url):
    """If URL starts with https://qvsfilestore/, replace with mount point /mnt/."""
    if url.startswith(QVSFILESTORE_URL_PREFIX):
        return QVSFILESTORE_MOUNT_POINT + url[len(QVSFILESTORE_URL_PREFIX):]
    return url


class QPALinkParser(HTMLParser):
    """HTML parser to extract .qpa file links from web pages."""
    def __init__(self):
        super().__init__()
        self.qpa_links = []
    
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for attr, value in attrs:
                if attr == 'href' and value.endswith('.qpa'):
                    self.qpa_links.append(value)


def is_url(path):
    """Check if the given path is a URL."""
    return path.startswith('http://') or path.startswith('https://')


def download_file(url, show_progress=True):
    """Download file from URL or read from local path (e.g. /mnt/ after qvsfilestore replacement)."""
    url = normalize_qpa_url(url)
    # If normalized to a local path, read from file
    if url.startswith('/'):
        try:
            if show_progress:
                print(f"  Reading from: {url}")
            with open(url, 'r', encoding='utf-8', errors='ignore') as f:
                return f.readlines()
        except Exception as e:
            print(f"  ❌ Error reading {url}: {e}")
            return None
    try:
        if show_progress:
            print(f"  Downloading from: {url}")
        # Create SSL context that doesn't verify certificates (for internal servers)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, context=ssl_context) as response:
            content = response.read().decode('utf-8', errors='ignore')
            return content.split('\n')
    except Exception as e:
        print(f"  ❌ Error downloading {url}: {e}")
        return None


def fetch_qpa_urls_from_html(base_url):
    """Fetch .qpa file URLs from an HTML page (URL or local path after qvsfilestore replacement)."""
    base_url = normalize_qpa_url(base_url)
    try:
        print(f"Fetching QPA file list from: {base_url}")
        if base_url.startswith('/'):
            with open(base_url, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            base_dir = os.path.dirname(base_url)
            parser = QPALinkParser()
            parser.feed(html_content)
            qpa_urls = []
            for link in parser.qpa_links:
                link = link.strip()
                if link.startswith('/'):
                    qpa_urls.append(QVSFILESTORE_MOUNT_POINT.rstrip('/') + link)
                else:
                    qpa_urls.append(os.path.normpath(os.path.join(base_dir, link)))
            return qpa_urls
        # Create SSL context that doesn't verify certificates (for internal servers)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(base_url, context=ssl_context) as response:
            html_content = response.read().decode('utf-8', errors='ignore')
        parser = QPALinkParser()
        parser.feed(html_content)
        qpa_urls = []
        for link in parser.qpa_links:
            if link.startswith('http://') or link.startswith('https://'):
                qpa_urls.append(normalize_qpa_url(link))
            else:
                qpa_urls.append(normalize_qpa_url(urllib.parse.urljoin(base_url, link)))
        return qpa_urls
    except Exception as e:
        print(f"❌ Error fetching HTML from {base_url}: {e}")
        return []


def parse_qpa_file(filepath, is_url_content=False, file_content=None):
    """Parse QPA test results file and count test outcomes.
    
    Args:
        filepath: Path to local file or URL (used for display name)
        is_url_content: If True, parse from file_content instead of filepath
        file_content: List of lines to parse (for URL content)
    """
    
    stats = defaultdict(int)
    test_details = []
    current_test = None
    current_test_content = []
    in_test_case = False
    
    filename = os.path.basename(filepath) if not is_url_content else filepath.split('/')[-1]
    print(f"Parsing {filename}...")
    
    line_num = 0
    
    # Choose data source: file_content for URLs, file for local paths
    if is_url_content and file_content is not None:
        lines = file_content
    else:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    
    # Process lines
    for line_num, line in enumerate(lines, 1):
        # Track progress every million lines
        if line_num % 1000000 == 0:
            print(f"  {filename}: Processed {line_num:,} lines...")
        
        # Start of test case
        if line.startswith('#beginTestCaseResult'):
            current_test = line.split(None, 1)[1].strip()
            current_test_content = [line]
            in_test_case = True
            stats['total'] += 1
        
        # Capture all lines in the test case
        elif in_test_case:
            current_test_content.append(line)
            
            # Test result
            if 'StatusCode=' in line:
                match = re.search(r'StatusCode="([^"]+)"', line)
                if match:
                    status = match.group(1)
                    stats[status] += 1
                    
                    # Extract result message
                    msg_match = re.search(r'>([^<]+)</Result>', line)
                    message = msg_match.group(1) if msg_match else ''
                    
                    # Store test details (only store actual failures)
                    if status == 'Fail':
                        test_details.append({
                            'name': current_test,
                            'status': status,
                            'message': message,
                            'full_content': ''.join(current_test_content),
                            'file': filename
                        })
            
            # End of test case
            if line.startswith('#endTestCaseResult'):
                in_test_case = False
                current_test_content = []
    
    print(f"  {filename}: Complete! Processed {line_num:,} lines total.")
    return stats, test_details


def generate_html_report(all_results, output_file='all_tests_report.html'):
    """Generate HTML report with summary table for all QPA files."""
    
    # Calculate totals
    grand_total = 0
    grand_passed = 0
    grand_failed = 0
    grand_not_supported = 0
    all_failed_tests = []
    
    for result in all_results:
        stats = result['stats']
        grand_total += stats.get('total', 0)
        grand_passed += stats.get('Pass', 0)
        grand_failed += stats.get('Fail', 0)
        grand_not_supported += stats.get('NotSupported', 0)
        all_failed_tests.extend(result['test_details'])
    
    # Calculate overall pass rate
    tested_count = grand_passed + grand_failed
    pass_rate = (grand_passed / tested_count * 100) if tested_count > 0 else 0
    
    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>All QPA Test Results Report</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        h1 {{
            margin: 0;
            font-size: 2.5em;
        }}
        .timestamp {{
            margin-top: 10px;
            opacity: 0.9;
            font-size: 0.9em;
        }}
        .summary {{
            padding: 30px;
            background: #f8f9fa;
        }}
        .summary h2 {{
            margin-top: 0;
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            text-align: center;
            border-left: 4px solid #667eea;
        }}
        .stat-card.pass {{
            border-left-color: #28a745;
        }}
        .stat-card.fail {{
            border-left-color: #dc3545;
        }}
        .stat-card.not-supported {{
            border-left-color: #ffc107;
        }}
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin: 10px 0;
        }}
        .stat-card.pass .stat-number {{
            color: #28a745;
        }}
        .stat-card.fail .stat-number {{
            color: #dc3545;
        }}
        .stat-card.not-supported .stat-number {{
            color: #ffc107;
        }}
        .stat-label {{
            color: #666;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        .pass-rate {{
            margin-top: 30px;
            padding: 20px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .progress-bar {{
            height: 40px;
            background: #e9ecef;
            border-radius: 20px;
            overflow: hidden;
            margin-top: 10px;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #28a745 0%, #20c997 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: bold;
            transition: width 1s ease;
        }}
        .file-summary {{
            padding: 30px;
        }}
        .file-summary h2 {{
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #dee2e6;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
        .failed-tests-table {{
            table-layout: fixed;
            width: 100%;
        }}
        .failed-tests-table td {{
            word-wrap: break-word;
            overflow-wrap: break-word;
            white-space: normal;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #495057;
            position: sticky;
            top: 0;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .num-col {{
            text-align: center;
            font-weight: 600;
        }}
        .pass-col {{
            color: #28a745;
        }}
        .fail-col {{
            color: #dc3545;
        }}
        .not-supported-col {{
            color: #ffc107;
        }}
        .status-badge {{
            display: inline-block;
            padding: 6px 16px;
            border-radius: 12px;
            font-size: 0.9em;
            font-weight: 600;
            white-space: nowrap;
            min-width: 60px;
        }}
        .status-fail {{
            background: #f8d7da;
            color: #721c24;
        }}
        .test-content {{
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 15px;
            margin-top: 10px;
            font-family: 'Courier New', monospace;
            font-size: 0.85em;
            white-space: pre-wrap;
            word-wrap: break-word;
            max-height: 400px;
            overflow-y: auto;
        }}
        .test-details-cell {{
            padding: 0 !important;
        }}
        .details {{
            padding: 30px;
        }}
        .details h2 {{
            color: #333;
            border-bottom: 3px solid #667eea;
            padding-bottom: 10px;
        }}
        .footer {{
            padding: 20px;
            text-align: center;
            background: #f8f9fa;
            color: #666;
            font-size: 0.9em;
        }}
        .pass-rate-cell {{
            font-weight: 600;
            font-size: 1.1em;
        }}
        .failed-file-link {{
            color: #dc3545;
            text-decoration: none;
            margin-left: 10px;
            font-weight: 600;
            transition: color 0.3s ease;
        }}
        .failed-file-link:hover {{
            color: #a71d2a;
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧪 All QPA Test Results Report</h1>
            <div class="timestamp">Generated on {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</div>
        </div>
        
        <div class="summary">
            <h2>📊 Overall Summary</h2>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">Total Tests</div>
                    <div class="stat-number">{grand_total:,}</div>
                </div>
                
                <div class="stat-card pass">
                    <div class="stat-label">Passed</div>
                    <div class="stat-number">{grand_passed:,}</div>
                </div>
                
                <div class="stat-card fail">
                    <div class="stat-label">Failed</div>
                    <div class="stat-number">{grand_failed:,}</div>
                </div>
                
                <div class="stat-card not-supported">
                    <div class="stat-label">Not Supported</div>
                    <div class="stat-number">{grand_not_supported:,}</div>
                </div>
            </div>
            
            <div class="pass-rate">
                <h3 style="margin-top: 0;">Overall Pass Rate</h3>
                <p style="margin: 5px 0; color: #666; font-size: 0.9em;">Based on {tested_count:,} tests (Pass + Fail, excluding Not Supported)</p>
                <p style="margin: 5px 0; color: #333; font-size: 1em;"><strong>{grand_passed:,} passed / {tested_count:,} tested</strong></p>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {pass_rate}%">
                        {pass_rate:.6f}%
                    </div>
                </div>
            </div>
"""
    
    # Add files with failures section
    files_with_failures = [r for r in all_results if r['stats'].get('Fail', 0) > 0]
    
    if files_with_failures:
        html += f"""
            <div style="margin-top: 30px; padding: 20px; background: #fff3cd; border-radius: 8px; border-left: 4px solid #ffc107;">
                <h3 style="margin-top: 0; color: #8B0000;">⚠️ List of failing Subtests</h3>
                <p style="color: #856404; margin-bottom: 15px;">Found {len(files_with_failures)} Subtest(s) with failures</p>
                
                <table>
                    <thead>
                        <tr>
                            <th style="width: 5%">#</th>
                            <th style="width: 60%">QPA File</th>
                            <th style="width: 15%" class="num-col">Failed Tests</th>
                            <th style="width: 20%" class="num-col">Action</th>
                        </tr>
                    </thead>
                    <tbody>
"""
        for idx, result in enumerate(files_with_failures, 1):
            failed_count = result['stats'].get('Fail', 0)
            html += f"""
                        <tr>
                            <td class="num-col">{idx}</td>
                            <td><code>{result['filename']}</code></td>
                            <td class="num-col fail-col">{failed_count}</td>
                            <td class="num-col">
                                <a href="#failed-tests" class="failed-file-link">View Details →</a>
                            </td>
                        </tr>
"""
        html += """
                    </tbody>
                </table>
            </div>
"""
    
    html += """
        </div>
        
        <div class="file-summary">
            <h2>📋 Test Results by File</h2>
            <p>Analyzed {len(all_results)} QPA file(s)</p>
            
            <table>
                <thead>
                    <tr>
                        <th style="width: 5%">#</th>
                        <th style="width: 30%">QPA File</th>
                        <th style="width: 10%" class="num-col">Total</th>
                        <th style="width: 10%" class="num-col">Passed</th>
                        <th style="width: 10%" class="num-col">Failed</th>
                        <th style="width: 12%" class="num-col">Not Supported</th>
                        <th style="width: 13%" class="num-col">Pass Rate</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    # Add rows for each file
    for idx, result in enumerate(all_results, 1):
        filename = result['filename']
        stats = result['stats']
        total = stats.get('total', 0)
        passed = stats.get('Pass', 0)
        failed = stats.get('Fail', 0)
        not_supported = stats.get('NotSupported', 0)
        
        file_tested = passed + failed
        file_pass_rate = (passed / file_tested * 100) if file_tested > 0 else 0
        
        html += f"""
                    <tr>
                        <td class="num-col">{idx}</td>
                        <td><code>{filename}</code></td>
                        <td class="num-col">{total:,}</td>
                        <td class="num-col pass-col">{passed:,}</td>
                        <td class="num-col fail-col">{failed:,}</td>
                        <td class="num-col not-supported-col">{not_supported:,}</td>
                        <td class="num-col pass-rate-cell">{file_pass_rate:.3f}%</td>
                    </tr>
"""
    
    html += """
                </tbody>
            </table>
        </div>
"""
    
    # Add detailed failed tests section if there are any failures
    if all_failed_tests:
        # Group failed tests by file
        tests_by_file = defaultdict(list)
        for test in all_failed_tests:
            tests_by_file[test['file']].append(test)
        
        html += f"""
        <div class="details" id="failed-tests">
            <h2>❌ Failed Tests (All Files)</h2>
            <p>Showing {len(all_failed_tests):,} failed test(s) across {len(tests_by_file)} file(s)</p>
"""
        
        global_idx = 1
        for file_idx, (filename, tests) in enumerate(tests_by_file.items(), 1):
            html += f"""
            <div style="margin-top: 30px;">
                <h3 style="background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 0; color: #856404;">
                    📄 File {file_idx}/{len(tests_by_file)}: <code style="color: #856404;">{filename}</code>
                    <span style="float: right; font-size: 0.9em;">({len(tests)} failed test(s))</span>
                </h3>
                <table class="failed-tests-table">
                    <thead>
                        <tr>
                            <th style="width: 5%; min-width: 30px;">#</th>
                            <th style="width: 45%; min-width: 200px;">Test Name</th>
                            <th style="width: 15%; min-width: 80px;">Status</th>
                            <th style="width: 35%; min-width: 150px;">Message</th>
                        </tr>
                    </thead>
                    <tbody>
"""
            
            for test in tests:
                # Escape HTML in the full content
                full_content = test.get('full_content', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    
                html += f"""
                        <tr class="test-row">
                            <td class="num-col">{global_idx}</td>
                            <td><code style="color: #dc3545; font-weight: 600;">{test['name']}</code></td>
                            <td class="num-col"><span class="status-badge status-fail">{test['status']}</span></td>
                            <td>{test['message']}</td>
                        </tr>
                        <tr>
                            <td colspan="4" class="test-details-cell">
                                <details>
                                    <summary style="cursor: pointer; padding: 10px; background: #f8f9fa; font-weight: 600;">
                                        📋 Show Full Test Details
                                    </summary>
                                    <div class="test-content">{full_content}</div>
                                </details>
                            </td>
                        </tr>
"""
                global_idx += 1
            
            html += """
                    </tbody>
                </table>
            </div>
"""
        
        html += """
        </div>
"""
    else:
        html += """
        <div class="details">
            <h2>✅ Test Results</h2>
            <div style="padding: 40px; text-align: center; background: #d4edda; border-radius: 8px; color: #155724;">
                <h3 style="margin: 0;">🎉 All tests passed or were skipped!</h3>
                <p style="margin-top: 10px;">No test failures detected across all files.</p>
            </div>
        </div>
"""
    
    html += """
        <div class="footer">
            <p>Report generated by QPA Test Results Analyzer</p>
        </div>
    </div>
</body>
</html>
"""
    
    # Write HTML file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"\n✅ HTML report generated: {output_file}")


def default_report_name(original_source, normalized_source):
    """Derive report filename from source when not explicitly given."""
    if original_source.startswith('https://') or original_source.startswith('http://'):
        # URL: use number after Testcase_Logs/ if present
        m = re.search(r'Testcase_Logs/(\d+)', original_source)
        if m:
            return f"{m.group(1)}_report.html"
        return 'all_tests_report.html'
    # Local path: use last folder name
    path = normalized_source.rstrip(os.sep).rstrip('/')
    last_folder = os.path.basename(path) if path else 'report'
    # Sanitize for filename (e.g. no path separators)
    last_folder = re.sub(r'[<>:"/\\|?*]', '_', last_folder) or 'report'
    return f"{last_folder}_report.html"


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_all_qpa.py <results_folder|url> [output_html]")
        print("\nExamples:")
        print("  Local folder:  python parse_all_qpa.py ./logs_vk/   -> logs_vk_report.html")
        print("  URL with Testcase_Logs/63203/... -> 63203_report.html")
        sys.exit(1)
    
    original_source = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    source = normalize_qpa_url(original_source)
    
    if output_file is None:
        output_file = default_report_name(original_source, source)
    
    qpa_files = []
    is_url_source = False
    
    if source.startswith('/'):
        # Local path (e.g. after replacing https://qvsfilestore/ with /mnt/)
        if os.path.isfile(source):
            if source.endswith('.qpa'):
                print(f"\n{'='*70}")
                print(f"Processing single QPA file from path")
                print(f"{'='*70}\n")
                qpa_files = [source]
            else:
                # e.g. HTML index page on mount
                print(f"\n{'='*70}")
                print(f"Fetching QPA file list from local HTML")
                print(f"{'='*70}\n")
                qpa_files = fetch_qpa_urls_from_html(source)
                if not qpa_files:
                    print("❌ No .qpa files found in the HTML page")
                    sys.exit(1)
                def extract_number(p):
                    filename = p.split('/')[-1]
                    match = re.search(r'-(\d+)-of-', filename)
                    if match:
                        return int(match.group(1))
                    return 0
                qpa_files = sorted(qpa_files, key=extract_number)
                print(f"\n{'='*70}")
                print(f"Found {len(qpa_files)} QPA file(s)")
                print(f"{'='*70}\n")
        elif os.path.isdir(source):
            qpa_pattern = os.path.join(source, '*.qpa')
            qpa_files = glob.glob(qpa_pattern)
            def extract_number(filepath):
                filename = os.path.basename(filepath)
                match = re.search(r'-(\d+)-of-', filename)
                if match:
                    return int(match.group(1))
                return 0
            qpa_files = sorted(qpa_files, key=extract_number)
            if not qpa_files:
                print(f"❌ No .qpa files found in {source}")
                sys.exit(1)
            print(f"\n{'='*70}")
            print(f"Found {len(qpa_files)} QPA file(s) in {source}")
            print(f"{'='*70}\n")
        else:
            print(f"❌ Not a file or directory: {source}")
            sys.exit(1)
    else:
        is_url_source = is_url(source)
        if is_url_source:
            # Handle URL input
            if source.endswith('.qpa'):
                print(f"\n{'='*70}")
                print(f"Processing single QPA file from URL")
                print(f"{'='*70}\n")
                qpa_files = [source]
            else:
                print(f"\n{'='*70}")
                print(f"Fetching QPA files from HTML page")
                print(f"{'='*70}\n")
                qpa_files = fetch_qpa_urls_from_html(source)
                if not qpa_files:
                    print("❌ No .qpa files found on the HTML page")
                    sys.exit(1)
                def extract_number(url):
                    filename = url.split('/')[-1]
                    match = re.search(r'-(\d+)-of-', filename)
                    if match:
                        return int(match.group(1))
                    return 0
                qpa_files = sorted(qpa_files, key=extract_number)
                print(f"\n{'='*70}")
                print(f"Found {len(qpa_files)} QPA file(s)")
                print(f"{'='*70}\n")
        else:
            # Handle local folder (non-path input)
            qpa_pattern = os.path.join(source, '*.qpa')
            qpa_files = glob.glob(qpa_pattern)
            def extract_number(filepath):
                filename = os.path.basename(filepath)
                match = re.search(r'-(\d+)-of-', filename)
                if match:
                    return int(match.group(1))
                return 0
            qpa_files = sorted(qpa_files, key=extract_number)
            if not qpa_files:
                print(f"❌ No .qpa files found in {source}")
                sys.exit(1)
            print(f"\n{'='*70}")
            print(f"Found {len(qpa_files)} QPA file(s) in {source}")
            print(f"{'='*70}\n")
    
    # Parse all files (local or URL)
    all_results = []
    for qpa_source in qpa_files:
        if is_url_source:
            # Download and parse from URL
            file_content = download_file(qpa_source)
            if file_content:
                stats, test_details = parse_qpa_file(qpa_source, is_url_content=True, file_content=file_content)
                all_results.append({
                    'filename': qpa_source.split('/')[-1],
                    'filepath': qpa_source,
                    'stats': stats,
                    'test_details': test_details
                })
        else:
            # Parse from local file
            stats, test_details = parse_qpa_file(qpa_source)
            all_results.append({
                'filename': os.path.basename(qpa_source),
                'filepath': qpa_source,
                'stats': stats,
                'test_details': test_details
            })
    
    # Generate HTML report
    generate_html_report(all_results, output_file)
    
    # Print summary table to console
    print("\n" + "="*120)
    print("TEST RESULTS SUMMARY BY FILE")
    print("="*120)
    print(f"{'#':<5} {'File':<35} {'Total':>10} {'Passed':>10} {'Failed':>10} {'Not Supp.':>12} {'Pass Rate':>12}")
    print("-"*120)
    
    grand_total = 0
    grand_passed = 0
    grand_failed = 0
    grand_not_supported = 0
    
    for idx, result in enumerate(all_results, 1):
        filename = result['filename']
        stats = result['stats']
        total = stats.get('total', 0)
        passed = stats.get('Pass', 0)
        failed = stats.get('Fail', 0)
        not_supported = stats.get('NotSupported', 0)
        
        grand_total += total
        grand_passed += passed
        grand_failed += failed
        grand_not_supported += not_supported
        
        tested = passed + failed
        pass_rate = (passed / tested * 100) if tested > 0 else 0
        
        print(f"{idx:<5} {filename:<35} {total:>10,} {passed:>10,} {failed:>10,} {not_supported:>12,} {pass_rate:>11.3f}%")
    
    print("-"*120)
    tested_total = grand_passed + grand_failed
    overall_pass_rate = (grand_passed / tested_total * 100) if tested_total > 0 else 0
    print(f"{'TOTAL':<5} {'':<35} {grand_total:>10,} {grand_passed:>10,} {grand_failed:>10,} {grand_not_supported:>12,} {overall_pass_rate:>11.3f}%")
    print("="*120)
    
    # Print failed test details if any
    all_failed = []
    for result in all_results:
        all_failed.extend(result['test_details'])
    
    if all_failed:
        print("\n" + "="*120)
        print(f"FAILED TEST DETAILS ({len(all_failed)} test(s) across all files)")
        print("="*120)
        for idx, test in enumerate(all_failed, 1):
            print(f"\n[{idx}] File: {test['file']}")
            print(f"    Test: {test['name']}")
            print(f"    Status: {test['status']}")
            print(f"    Message: {test['message']}")
            print("\n    Full Test Content:")
            print("    " + "-" * 70)
            for line in test.get('full_content', 'No content available').split('\n'):
                print(f"    {line}")
            print("    " + "-" * 70)


if __name__ == '__main__':
    main()
