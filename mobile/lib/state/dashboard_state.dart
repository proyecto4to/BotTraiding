// Dashboard data: portfolio snapshot + circuit breaker, loaded via the
// gateway. Degrades gracefully (error message, keeps last data) when
// upstream services are down.

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../models/portfolio.dart';
import '../models/risk.dart';

class DashboardState extends ChangeNotifier {
  DashboardState(this._api);

  final ApiClient _api;

  PortfolioState? portfolio;
  CircuitBreakerStatus? breaker;
  bool loading = false;
  String? error;

  Future<void> load(String accountId) async {
    loading = true;
    notifyListeners();
    try {
      final json = await _api.get('/api/portfolio/$accountId');
      portfolio = PortfolioState.fromJson(json as Map<String, dynamic>);
      error = null;
    } on ApiException {
      error = 'portfolio-engine is not responding';
    }
    try {
      final json = await _api.get('/api/risk/circuit-breaker/$accountId');
      breaker = CircuitBreakerStatus.fromJson(json as Map<String, dynamic>);
    } on ApiException {
      breaker = null;
    }
    loading = false;
    notifyListeners();
  }
}
