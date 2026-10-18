# Alpha alert review

Synthetic development fixture. Not an equipment-control instruction.

## purpose

This procedure applies to every asset at the alpha site. It tells the reviewer how to investigate the alerts raised
on one asset over a fixed interval and how to turn what was found into a reviewable incident draft. It never tells
anyone to operate equipment, acknowledge alarms or change limits. It is the general procedure for the alpha site:
when an asset has no procedure of its own for a kind of alert, this one decides what the reviewer reads and writes.
Reviewers new to the alpha site read this procedure before their first review and ask the site's review lead when a
step is unclear; the lead's answer is noted beside the step.

## interval

Fix the observation interval before reading alerts; the default interval is the last 24 hours ending at the time the
request was made. Read every alert on the asset inside that interval, including cleared ones, and nothing outside it.
If more alerts exist than can be shown, say so and keep the count of the hidden ones. The interval is stated in every
draft as an absolute start and end time, never as a relative phrase that a later reader could misread.

## repeated-alerts

Repeated alerts on one asset may be summarized in one reviewable incident draft; the alert count alone does not
establish root cause. Group the alerts by kind, give the first and last time of each group, and keep the original
alert identifiers so that the reviewer can open each one.

## evidence

Cite the asset, the interval, the alert count and the permitted source versions in every draft. Preserve uncertainty:
a missing reading, a truncated list or an unavailable status is stated, never guessed. A draft without at least one
permitted source is not sent for review.

## handoff

A different authorized reviewer must inspect the exact draft before it is handed to the incident destination. The
reviewer approves or rejects the draft as written; any change makes a new draft that needs a new review. The person
who asked for the investigation cannot approve their own draft.
