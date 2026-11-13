# Watchyard 0.8.16

Person activity could produce a new Telegram alert just before another camera
confirmed that it belonged to an already reported group. This occurred at
Portão on 12 November at 13:45:41 and 14:14:47 WET.

A likely return now has up to four seconds from detection to collect another
camera's evidence. It joins the existing group only when its position and
appearance match a recent participant, the group has recent observations,
and a simultaneous second view independently continues that group along an
established route. Conflicting appearance, competing visible people, weak
timing-only links and ambiguous groups prevent the new association.

First alerts remain immediate. Without corroboration, the new alert proceeds
at the original deadline, including after a restart. Other notification
providers continue immediately. Telegram still sends to an account that has
not received the first alert and permits a silent-to-audible upgrade.
The vehicle-motion checks and existing group IDs are preserved.

Validation:

- 166 tests passed, including 18 added cases for corroboration, competing
  people, missing evidence, restart recovery, multiple recipients and providers.
- Chronological metadata replay of 68 events from 12 November removed exactly
  the two identified Portão repeat alerts and introduced no new alerts.
  The baseline replay produced 28 alerts and this version produced 26. The live
  system sent 25 that day: intermediate frame observations were not retained,
  so replay removes unavailable later colour/position samples and caps visible
  intervals at simulated time. These numbers are not a production reduction
  estimate or a full detection-accuracy evaluation.
- Installed on the Mac; all four cameras resumed analysis, health reported
  ready, both Telegram accounts remained paired, and the event queue was empty.

Remaining work: larger gaps, long yard activities and infrared/colour handoffs
can still create separate person groups. Measure new events and verify separate
arrivals before broadening the association rules.

The bounded wait follows the general late-evidence principle documented for
[Alertmanager grouping](https://prometheus.io/docs/alerting/latest/configuration/#route).
The four-second limit and camera-specific evidence checks are Watchyard's
implementation choices, validated against this pilot's examples.
