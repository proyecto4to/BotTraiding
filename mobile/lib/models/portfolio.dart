// DTOs mirroring portfolio-engine responses (GET /api/portfolio/{account}).

import 'auth.dart' show asDouble;

class AccountState {
  const AccountState({
    required this.accountId,
    required this.balance,
    required this.equity,
    required this.marginUsed,
    required this.freeMargin,
    required this.currency,
  });

  factory AccountState.fromJson(Map<String, dynamic> json) => AccountState(
        accountId: json['account_id'] as String? ?? '',
        balance: asDouble(json['balance']),
        equity: asDouble(json['equity']),
        marginUsed: asDouble(json['margin_used']),
        freeMargin: asDouble(json['free_margin']),
        currency: json['currency'] as String? ?? 'USD',
      );

  final String accountId;
  final double balance;
  final double equity;
  final double marginUsed;
  final double freeMargin;
  final String currency;
}

class Position {
  const Position({
    required this.symbol,
    required this.quantity,
    required this.averagePrice,
    required this.unrealizedPnl,
  });

  factory Position.fromJson(Map<String, dynamic> json) => Position(
        symbol: json['symbol'] as String? ?? '',
        quantity: asDouble(json['quantity']),
        averagePrice: asDouble(json['average_price']),
        unrealizedPnl: asDouble(json['unrealized_pnl']),
      );

  final String symbol;
  final double quantity;
  final double averagePrice;
  final double unrealizedPnl;
}

class DrawdownReport {
  const DrawdownReport({
    required this.equity,
    required this.peakEquity,
    required this.currentDrawdown,
    required this.floatingDrawdown,
  });

  factory DrawdownReport.fromJson(Map<String, dynamic> json) => DrawdownReport(
        equity: asDouble(json['equity']),
        peakEquity: asDouble(json['peak_equity']),
        currentDrawdown: asDouble(json['current_drawdown']),
        floatingDrawdown: asDouble(json['floating_drawdown']),
      );

  final double equity;
  final double peakEquity;
  final double currentDrawdown;
  final double floatingDrawdown;
}

class PortfolioState {
  const PortfolioState({
    required this.account,
    required this.positions,
    required this.drawdown,
    required this.realizedPnl,
    required this.unrealizedPnl,
    required this.pnlDaily,
    required this.pnlWeekly,
    required this.pnlMonthly,
  });

  factory PortfolioState.fromJson(Map<String, dynamic> json) => PortfolioState(
        account: AccountState.fromJson(
            json['account'] as Map<String, dynamic>? ?? const {}),
        positions: (json['positions'] as List<dynamic>? ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(Position.fromJson)
            .toList(growable: false),
        drawdown: DrawdownReport.fromJson(
            json['drawdown'] as Map<String, dynamic>? ?? const {}),
        realizedPnl: asDouble(json['realized_pnl']),
        unrealizedPnl: asDouble(json['unrealized_pnl']),
        pnlDaily: asDouble(json['pnl_daily']),
        pnlWeekly: asDouble(json['pnl_weekly']),
        pnlMonthly: asDouble(json['pnl_monthly']),
      );

  final AccountState account;
  final List<Position> positions;
  final DrawdownReport drawdown;
  final double realizedPnl;
  final double unrealizedPnl;
  final double pnlDaily;
  final double pnlWeekly;
  final double pnlMonthly;
}
