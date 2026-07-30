# AI Nurture End-to-End Business Flow

## Purpose

This document explains the full business flow for how AI nurture works in Phase
One.

It is written for client, product, operations, and delivery conversations. It
focuses on business behavior, not technical implementation.

## What this document covers

This document explains:

- how the system understands different kinds of leads
- when nurture may start and when it may not
- the difference between dormant and paused-search leads
- what happens when a lead replies
- when a human agent must take over
- what the business team can review or override
- what the system will and will not do in Phase One

## The business goal

The goal is to let AI help the brokerage re-engage leads safely and
consistently, while keeping human agents in control of important moments.

The system should:

- recognize whether a lead is dormant, paused, active, or unsafe to contact
- start the right kind of follow-up only when the lead meets the configured
  start rule and passes the required safety checks
- stop AI outreach when a lead becomes active or wants a person
- let the team review and correct AI decisions in the dashboard

## Core business concepts

### Configured AI nurture tag

The configured AI nurture tag is the start signal that allows a lead to enter AI
nurture.

Without this tag, a lead may be understood by the system, but nurture must not
start.

### Dormant lead

A dormant lead is a lead the brokerage has not heard from for some time and for
whom there is no known reason for the silence.

The business does not yet know whether the lead is still interested, has paused,
has moved on, or needs a human.

### Paused-search lead

A paused-search lead is still potentially viable, but there is a known reason
they are not actively moving right now.

The system stores that reason as a paused-search profile on the lead, including:

- the reason code, such as `waiting_for_rates`, `waiting_for_inventory`, `timing_not_right`,
  `financial_prep`, `personal_life_timing`, `rented_temporarily`, or `other_known_pause`
- the earliest re-engagement date, if the lead mentioned one
- a human-readable timing label, such as "after the lease ends" or "next quarter"
- the source of the decision, such as AI classification, operator override, or a resolved
  routing review
- a history of every profile change so the team can see what changed and when

Examples include:

- waiting for rates
- waiting for better inventory
- timing not right
- financial preparation
- personal life timing
- temporarily renting before resuming the search

### Human handoff

Human handoff means AI should stop and a person should take over.

This applies when a lead:

- shows meaningful current interest
- asks to speak with a person
- requests listings, a showing, or a call
- begins a buying or selling conversation that should be handled by an agent

### Blocked lead

A blocked lead is a lead the system must not contact automatically because of a
business or compliance reason.

Examples include:

- opt-out
- do-not-contact
- suppression rules, such as an SMS opt-out or email unsubscribe
- missing consent for the intended channel
- active human ownership that should stop automation

Hard suppression is checked before any AI classification runs. If the lead is
flagged do-not-contact or carries a suppression type for the channel, the route
is `blocked` immediately and the lead does not enter AI nurture.

### Review hold

A review hold is used when the system cannot safely decide the right path.

Examples include:

- unclear conversation meaning
- conflicting signals
- missing timing details
- AI confidence too low for a trusted business decision

## End-to-end business flow

## Step 1: The system reads the lead's recent context

The system looks at recent approved conversation context and determines the
lead's current situation.

At this stage, the system is answering a business question:

**What kind of lead is this right now?**

Possible business answers include:

- paused-search
- dormant
- needs human handoff
- blocked from automation
- unclear and needs review

## Step 2: AI classifies the lead first

AI is the first layer that interprets the conversation.

Its job is to identify:

- whether the lead is paused or simply dormant
- whether a known pause reason exists
- whether timing has been mentioned
- whether the lead is now active and should go to a person
- whether the situation is too unclear to trust automatically

This gives the business a current working understanding of the lead before a
human opens the dashboard.

## Step 3: The system stores and shows that understanding

The AI result is stored durably and shown in the dashboard so the team can see:

- the lead's current state
- why the system believes that state is correct
- any known timing information
- whether the current state came from AI or a human override
- the history of changes over time

This means the team does not have to re-read the whole conversation every time
to understand where the lead stands.

## Step 4: Humans can review and override

The business team can review what AI concluded and change it when needed.

Examples of allowed human actions:

- confirm the AI decision
- change a lead from dormant to paused-search
- change the paused-search reason
- update expected timing
- clear a wrong classification
- reject an AI interpretation and require review

When a human changes the lead state, that human decision becomes the trusted
current business truth until new evidence is reviewed.

## Step 5: Nurture still cannot start without the configured tag

This is a hard business rule.

Even if AI is very confident that a lead is paused-search or dormant, nurture
must not start unless the configured AI nurture tag is present on the lead.

This keeps two separate ideas clear:

- **understanding the lead**
- **meeting the start rule for AI nurture**

The system may understand a lead before the configured start tag allows nurture
to begin.

## Step 6: Once the tag is present, the system chooses the right path

When the configured AI nurture tag is present, the system decides which path the
lead should enter.

The decision order is:

1. hard suppression checked before classification
2. human handoff or blocked state from AI classification
3. paused-search from AI classification
4. dormant from AI classification
5. review hold if the classification is ambiguous, rejected, or lacks enough evidence

This order matters.

It means:

- a hot lead tagged by mistake does not start AI nurture
- a clearly paused-search lead is not treated like a generic dormant lead
- a silent lead with no known pause reason can go into dormant re-engagement
- an existing paused-search profile is not silently cleared by a later `dormant`
  or `review_hold` classification; the route stays paused-search until the
  evidence is strong enough for a higher-priority outcome
- human handoff and blocked always win over an existing paused-search profile

If a lead is classified as dormant, the configured tag is present, and no
higher-priority blocker or handoff condition exists, the lead enters the
dormant journey automatically.

If a lead is classified as paused-search, the configured tag is present, and no
higher-priority blocker or handoff condition exists, the lead enters a
paused-search journey that follows the reason and timing stored in the profile.

## Step 7: Dormant leads follow a dormant re-engagement journey

Dormant leads are leads who went quiet for no known reason.

The business goal of dormant outreach is to find out:

- whether the lead is still interested
- whether their timing changed
- whether their search criteria changed
- whether they want help from an agent
- whether follow-up should stop

The dormant journey should feel light and respectful, not aggressive.

When a dormant lead enters this journey, the message should be written using the
lead's recent conversation context and any already-known preferences or timing
signals, rather than sounding generic or disconnected from prior history.

The current implementation does this through the shared outbound drafting path,
using the lead's approved summary and recent approved conversation context while
adding dormant-specific instructions to keep the message low-pressure.

Examples of appropriate dormant outreach include:

- checking if the lead is still interested in buying or selling
- asking whether their plans changed
- offering to reconnect them with their assigned agent
- inviting them to reply if they want updated help

## Step 8: Paused-search leads follow a paused-search journey

Paused-search leads are different because the business already knows why the
lead is waiting.

The paused-search journey should reflect that known context.

Examples:

- a lead waiting for rates may get periodic low-pressure check-ins
- a lead waiting for inventory may get lighter market-aware touches
- a lead renting temporarily may get a longer quiet period and later
  reactivation
- a lead delayed by life timing may get a respectful future follow-up cadence

Paused-search follow-up should acknowledge the lead's timing rather than treat
them like a generic silent lead.

The system uses reason-specific email templates. For each of the seven supported
pause reasons, there is a maintenance-style template for low-pressure check-ins
and a reactivation-style template for follow-up near the expected re-engagement
window. The correct template is selected automatically based on the lead's
paused-search reason and the current cadence step. Email subject and body are
still drafted by the approved model, but the template supplies the fixed framing,
placeholder variables such as the lead's first name, and the prompt instructions
so the message stays consistent with the known reason.

These messages should also reflect the lead's recent conversation context so the
outreach feels consistent with what the lead already shared.

## Step 9: Any meaningful reply triggers a fresh decision

If a lead in either dormant or paused-search nurture replies, the system must
not blindly continue the old plan.

Instead, it must read the updated conversation and make a fresh business
decision.

If the updated decision no longer supports dormant automation, the system must
stop the planned continuation before sending another AI follow-up.

The AI continuation path also has a hard back-and-forth cap. Once the cap is
reached, the workflow pauses so a human can review instead of letting the
conversation drift.

Even when continuation is allowed, the final send-time gate re-checks the
channel. A message whose channel is blocked by opt-out, unsubscribe, or missing
consent is recorded as blocked rather than sent.

After a reply, the lead may:

- remain paused-search
- remain dormant
- move to human handoff
- become blocked
- move into review hold

This is important because a lead's situation can change quickly.

For example:

- a dormant lead may reply and reveal they were waiting for rates all along
- a paused-search lead may reply and say they are ready now
- either type of lead may reply and ask for a person immediately

## Step 10: Human handoff stops AI outreach

If the latest message shows real current interest or a request for human help,
AI must stop and the assigned agent must take over.

This includes situations such as:

- "Yes, I'm ready now"
- "Can someone call me?"
- "Send me homes in this area"
- "I want to see properties this weekend"
- "I'm thinking about selling my home too"

When this happens, the system should:

- stop pending AI outreach
- mark the lead for handoff
- notify the right agent
- preserve the latest context and summary for that agent

## Step 11: Safety rules still apply before every send

Even after a lead is classified and routed, the system must re-check whether a
message is still allowed before every outbound send.

Examples of things that can still stop a message:

- the lead opted out
- the lead replied after the message was scheduled
- an agent manually contacted the lead
- ownership changed
- quiet hours apply
- frequency limits were reached
- consent or contactability is no longer valid

The business should think of classification and routing as the plan, but send
eligibility as a final checkpoint every time.

The current implementation keeps this as a shared final gate: dormant outreach
still goes through the same locked pre-send safety decision immediately before
the provider call.

## Common business use cases

### Use case 1: Silent lead with no known reason

- the system sees no recent meaningful communication
- AI does not find a clear pause reason
- the configured tag is present
- the lead enters the dormant path
- outreach asks whether the lead is still interested and whether plans changed

### Use case 2: Lead says they want to wait for rates

- AI detects a clear paused-search reason
- the dashboard shows the lead as paused-search
- if the configured tag is present, the lead enters a paused-search journey
- outreach is timed and low-pressure rather than generic reactivation

### Use case 3: Lead is accidentally tagged while already active

- the configured tag is present
- AI sees active interest or a human-request signal
- the lead does not start nurture
- the lead goes straight to human handoff

### Use case 4: Dormant lead replies with a known reason

- the lead was in dormant nurture
- they reply and explain they are waiting until after a lease ends
- the system re-evaluates the conversation
- the lead moves from dormant to paused-search
- future outreach follows the paused-search path instead

### Use case 5: Paused-search lead replies and is ready now

- the lead was paused-search
- they reply with renewed intent
- the system re-evaluates the lead
- AI outreach stops
- the lead goes to handoff so an agent can take over

### Use case 6: Lead replies with an opt-out or block signal

- the lead replies with a stop or unsubscribe message
- the system blocks further automated outreach
- the lead is no longer allowed to continue in nurture until business rules say
  otherwise

### Use case 7: Agent disagrees with AI

- AI classifies the lead one way
- the agent or manager reviews the lead in the dashboard
- they change the state, timing, or reason
- that human decision becomes the current trusted state

## What the client should expect to see operationally

In day-to-day operations, the team should be able to see:

- which leads are dormant
- which leads are paused-search
- which leads were handed off to humans
- which leads are blocked
- which leads need review
- whether a lead's current status came from AI or a human
- what changed and when it changed

## What the business can control

The business should be able to control configured settings such as:

- which CRM tag is used to start AI nurture
- which paused-search reasons are used
- how paused-search reasons map to follow-up paths
- which dormant and paused-search outreach templates are used
- which channels are used
- review policies for uncertain cases
- who is allowed to override AI decisions

## What Phase One will do with listings and market information

In Phase One, the system may:

- ask whether the lead is still interested
- ask whether preferences changed
- offer to reconnect the lead with an agent
- send approved links or approved static resources from the brokerage

In Phase One, the system should not:

- invent listing recommendations
- claim specific market changes without an approved source
- behave like a full MLS or IDX property-matching assistant unless that is added
  later

## What Phase One will not do

Phase One will not:

- let nurture start without the configured AI nurture tag
- let AI override opt-out, suppression, or human-control rules
- let AI continue once a lead clearly needs a human
- create an unrestricted freeform automation engine
- replace the agent in active buying or selling conversations

## Summary

The business flow is:

1. AI understands the lead first
2. the system shows that understanding in the dashboard
3. humans can review or override it
4. nurture still cannot start without the configured tag
5. once tagged, the system routes the lead into the correct path
6. dormant and paused-search leads follow different journeys
7. every meaningful reply triggers a fresh decision
8. active interest always moves the lead back to a human

That is the end-to-end Phase One business behavior the client should expect.

## Implementation note

The routing decision is made by a dedicated `route_ai_nurture_lead` use case that is
called from the shared tag-enrollment entry point. It records each routing decision
and the classification evidence that supported it, so the decision is auditable. The
possible routes are: `dormant`, `paused_search`, `human_handoff`, `review_hold`, and
`blocked`. The `dormant` and `paused_search` routes enter automated workflows;
`human_handoff`, `review_hold`, and `blocked` stop at the gate and surface the reason
for review.

When a route lands in `review_hold`, the system creates a routing-review record for
the team. An authorized user can resolve that review by routing the lead to
`paused_search` or `dormant`; any older pending review for the same lead is then
marked superseded. Resolved and superseded reviews are visible in the lead detail
history.

Dormant and paused-search drafting both reuse the shared outbound planning and send
pipeline. The drafting step receives journey-specific guidance plus recent approved
conversation context, while reply-time continuation now re-runs routing with the
latest inbound reply before another automated follow-up can be sent. Every planned
send still passes the final pre-send safety gate, which re-checks opt-out,
channel consent, frequency limits, quiet hours, and ownership at execution time.