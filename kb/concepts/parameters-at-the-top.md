---
title: Put the settings in parameters at the top
tags: [parameters, basics]
---
Anything a trader may want to change belongs in a parameter at the top
of the formula: lengths, thresholds, times, stop sizes. Then the logic
below never needs editing, and the value can be changed from the
Parameters window without touching the code.

```afl
FastLen = Param("Fast average", 20, 5, 100, 1);
SlowLen = Param("Slow average", 50, 10, 300, 1);
UseFilter = ParamToggle("Trend filter", "Off|On", 1);
ExitTime = ParamTime("Exit time", "15:15");
LineColour = ParamColor("Line colour", colorBlue);
```

Param takes the label, the default, the lowest and highest values, and
the step. ParamToggle gives 0 or 1. ParamTime gives a time as a number
in the same form as TimeNum. ParamList offers a list of choices and
ParamStr takes text.

Give each parameter a label that says what it is. The label is what the
user sees.

Optimize marks a value for the optimiser to vary. Outside an
optimisation it simply returns its default:

```afl
Length = Optimize("Length", 20, 5, 60, 5);
```

Parameters are single numbers, not arrays, so they are safe to use in an
`if` statement.
