---
title: The time in your data may not be the exchange's time
tags: [intraday, time, data]
---
TimeNum does not know what time it is at the exchange. It reads the time
stamps in your data. If the data vendor stamps bars in another time
zone, every time filter in the formula is off by that difference.

Data for an Indian exchange that is stamped in UTC would show the 9:15
open as 03:45. A filter written for 91500 would then never match, or
would match the wrong part of the day.

Two more things vary between data feeds:

- Whether a bar's time is the start of its interval or the end. A
  5-minute bar covering 9:15 to 9:20 may be stamped 9:15 or 9:20.
- Whether pre-open or after-hours bars are present.

Before trusting a time filter, look at an intraday chart and read the
time of the first and last bar of a session. They should match the
exchange's session times. If they do not, either correct the shift in
AmiBroker's intraday database settings or change the times in the
formula's parameters.

This is one more reason to keep every session time in a parameter at the
top of the formula.
