---
title: Drawing on the chart with Plot and PlotShapes
tags: [plot, chart]
---
Plot draws an array. It takes the array, a name for the title line, a
colour and a style.

```afl
Fast = EMA(Close, 9);
Slow = EMA(Close, 21);
Plot(Close, "Close", colorDefault, styleCandle);
Plot(Fast, "Fast EMA", colorGreen, styleLine);
Plot(Slow, "Slow EMA", colorRed, styleLine | styleThick);
```

Styles are combined with `|`. Common ones are styleLine, styleCandle,
styleBar, styleHistogram, styleDots, styleThick and styleDashed.
styleOwnScale gives the plot its own vertical scale, which suits an
oscillator drawn over price, and styleNoLabel hides the value label.

PlotShapes draws markers on the bars where its first argument is not
zero. Multiplying a signal by a shape gives the shape on signal bars and
nothing elsewhere.

```afl
Buy = Cross(Fast, Slow);
Sell = Cross(Slow, Fast);
PlotShapes(Buy * shapeUpArrow, colorGreen, 0, Low);
PlotShapes(Sell * shapeDownArrow, colorRed, 0, High);
```

The fourth argument is the price the marker sits at: Low puts it under
the bar and High above it.

If the signals are conditions that stay true for many bars, clean them
with ExRem first, or an arrow appears on every bar.

`_SECTION_BEGIN` and `_SECTION_END` group the parameters of a part of
the formula under one heading in the Parameters window.
