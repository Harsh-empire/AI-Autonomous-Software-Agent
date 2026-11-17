## Description
Briefly describe the intent and nature of the proposed changes.

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] Security fix (addressing an access control, path traversal, or sandbox issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing behavior to change)
- [ ] Documentation update

## Verification & Testing
- [ ] `pytest tests/ -v` passes locally on all test suites.
- [ ] `pytest tests/test_path_traversal.py -v` passes.
- [ ] No hardcoded secrets, tokens, or local machine paths included.
- [ ] Benchmark results (if included) are generated from actual runs.

## Related Issues
Fixes #(issue number)
