# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x     | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Use [GitHub's private vulnerability reporting](https://github.com/fthelen/contribnote/security/advisories/new) to submit your report with:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested fixes (optional)

You can expect:
- **Acknowledgment** within 48 hours
- **Status update** within 7 days
- **Resolution timeline** based on severity

## Security Best Practices for Users

### API Key Protection

- **Never commit API keys** to version control
- Use environment variables (`OPENAI_API_KEY`) or the system keychain
- The `.env` file is gitignored by default—keep it that way
- Rotate keys immediately if you suspect exposure

### Input File Handling

- This application processes Excel files locally—no file contents are uploaded
- Only security identifiers (ticker, name) and time periods are sent to OpenAI
- Portfolio codes (PORTCODE) are **never** sent to the API

### Output Security

- Generated commentary files may contain sensitive portfolio information
- Store output files according to your organization's data policies
- Log files contain run metadata but no API keys or portfolio weights

## Dependencies

This project uses third-party dependencies. We recommend:
- Keeping dependencies updated (`pip install --upgrade -r requirements.txt`)
- Reviewing the [requirements.txt](requirements.txt) for the dependency list
- Using a virtual environment to isolate dependencies
