---
title: IIf chooses between two values bar by bar
tags: [iif, arrays]
---
IIf takes a condition and two values. For each bar it gives the first
value where the condition is true and the second where it is false. The
result is an array.

```afl
Avg = MA(Close, 50);
BarColour = IIf(Close > Avg, colorGreen, colorRed);
Plot(Close, "Close", BarColour, styleBar);
```

IIf is not a statement that runs one branch or the other. Both values
are worked out for every bar, and IIf then picks between them. So it
cannot be used to skip a calculation or to decide which variable gets
assigned.

IIf calls can be nested when there are three outcomes:

```afl
Momentum = RSI(14);
Zone = IIf(Momentum > 70, 1, IIf(Momentum < 30, -1, 0));
```

Use the `if` statement only when the condition is a single number, for
example a parameter the user picked or a value taken with LastValue.
