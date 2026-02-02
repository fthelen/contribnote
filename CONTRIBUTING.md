# Contributing to Commentary Generator

Thank you for your interest in contributing! This document provides guidelines for contributing to the project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/commentary.git
   cd commentary
   ```
3. **Create a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```
4. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Development Workflow

### Making Changes

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes
3. Test your changes manually with the sample Excel files
4. Commit with a clear message:
   ```bash
   git commit -m "Add feature: description of what you added"
   ```

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) for Python code
- Use type hints where practical
- Keep functions focused and well-documented
- Add docstrings to public functions and classes

### Commit Messages

Use clear, descriptive commit messages:
- `Add feature: new thinking level selector`
- `Fix: handle empty Excel rows gracefully`
- `Docs: update configuration reference`
- `Refactor: simplify API retry logic`

## Pull Request Process

1. **Update documentation** if your change affects user-facing behavior
2. **Test thoroughly** with both sample files
3. **Push your branch** to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```
4. **Open a Pull Request** against the `main` branch
5. **Describe your changes** clearly in the PR description

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Self-reviewed the code changes
- [ ] Added/updated documentation as needed
- [ ] Tested with sample Excel files
- [ ] No sensitive data (API keys, real portfolio data) included

## Reporting Issues

### Bug Reports

When reporting bugs, please include:
- Python version (`python --version`)
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Error messages (if any)

### Feature Requests

Feature requests are welcome! Please describe:
- The problem you're trying to solve
- Your proposed solution
- Any alternatives you've considered

## Questions?

If you have questions about contributing, feel free to open a discussion or issue on GitHub.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
