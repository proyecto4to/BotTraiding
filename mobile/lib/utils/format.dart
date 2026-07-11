// Display formatting helpers (no intl dependency: keep the skeleton lean).

String fmtMoney(double value, [String currency = 'USD']) {
  final sign = value < 0 ? '-' : '';
  final fixed = value.abs().toStringAsFixed(2);
  final parts = fixed.split('.');
  final digits = parts[0];
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  final symbol = currency == 'USD' ? r'$' : '$currency ';
  return '$sign$symbol$buffer.${parts[1]}';
}

/// Formats a fraction (0.0132 -> "1.32%").
String fmtPct(double value, [int digits = 2]) =>
    '${(value * 100).toStringAsFixed(digits)}%';

String fmtNum(double value, [int digits = 2]) => value.toStringAsFixed(digits);
