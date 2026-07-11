// Strategy list + enable/disable toggles (GET/PATCH /api/strategies).

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../models/strategy.dart';

class StrategiesState extends ChangeNotifier {
  StrategiesState(this._api);

  final ApiClient _api;

  List<StrategySummary> strategies = const [];
  bool loading = false;
  String? error;
  String? togglingKey;

  Future<void> load() async {
    loading = true;
    notifyListeners();
    try {
      final json = await _api.get('/api/strategies');
      strategies = (json as List<dynamic>)
          .whereType<Map<String, dynamic>>()
          .map(StrategySummary.fromJson)
          .toList(growable: false);
      error = null;
    } on ApiException {
      error = 'strategy-engine is not responding';
      strategies = const [];
    }
    loading = false;
    notifyListeners();
  }

  Future<String?> toggle(StrategySummary strategy, bool enabled) async {
    togglingKey = strategy.key;
    notifyListeners();
    String? failure;
    try {
      final json = await _api.patch(
        '/api/strategies/${strategy.key}',
        body: {'enabled': enabled},
      ) as Map<String, dynamic>;
      final updated = StrategySummary.fromJson(json);
      strategies = strategies
          .map((s) => s.key == updated.key ? s.copyWith(enabled: updated.enabled) : s)
          .toList(growable: false);
    } on ApiException catch (err) {
      failure = err.message;
    }
    togglingKey = null;
    notifyListeners();
    return failure;
  }
}
