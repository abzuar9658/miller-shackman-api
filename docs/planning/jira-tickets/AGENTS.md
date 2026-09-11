# Ticket PRs and manual testing

Follow these instructions for every ticket in this directory, including changes in either repository.

## Verify the changes yourself first

- Deliver **one ticket per PR**. Follow the README's dependencies and approvals; never mix Class A and B.
- Add or update automated tests and run them. Then **manually exercise the changed journey yourself**
  on the PR's build. Passing automated tests alone is not manual verification.
- Use an authorized local or staging environment, synthetic leads and sandbox/sink providers.
  Do not contact real customers or change production data without separate explicit authorization.
- Check the intended change, one normal unchanged journey, and relevant safety, failure and recovery
  cases. Refresh or reopen the page to confirm the result was saved.
- Record the version, environment, actions and actual results. Fix failures and verify again.
  If blocked, say **Not verified**, explain what is missing, and do not claim the ticket is done.

## Give the stakeholder a simple checklist

After verification, include this handoff in **both the PR description and your final response**:

1. **What changed:** one or two sentences explaining the business outcome.
2. **Before testing:** where to test, the version, required user role and prepared test lead/setup.
   Never include passwords, secrets or real customer details.
3. **What I verified:** the manual checks actually performed, their Pass / Fail / Not run results,
   safe supporting evidence and any remaining limitations. Do not pre-check the stakeholder's list.
4. **Manual testing checklist:** short, unchecked steps covering the user-visible acceptance outcomes,
   an unchanged working case and relevant protections/failure recovery. Use this format:

- [ ] **Do:** a specific action. **Expect:** the visible result, including what must not happen.

Use plain business language and exact page/button names. Do not require commands, database access
or reading logs. Prepare developer-only setup yourself; explain checks that cannot be reproduced
through the normal interface and provide their verification evidence separately. Stakeholder testing
is a second check, not a substitute for the agent's own verification or release approval.

Use --arch arm64 in case of architectural mismatch. It always works this way.