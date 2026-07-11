// Alerts: risk events feed. GET /api/risk/events/{account} does not exist
// in risk-engine yet (rows are persisted, endpoint pending) so this state
// degrades to an "unavailable" empty list until the backend lands.

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../models/risk.dart';

class AlertsState extends ChangeNotifier {
  AlertsState(this._api);

  final ApiClient _api;

  List<RiskEvent> events = const [];
  bool loading = false;
  bool unavailable = false;

  Future<void> load(String accountId) async {
    loading = true;
    notifyListeners();
    try {
      final json = await _api.get(
        '/api/risk/events/$accountId',
        query: {'limit': '100'},
      );
      events = (json as List<dynamic>)
          .whereType<Map<String, dynamic>>()
          .map(RiskEvent.fromJson)
          .toList(growable: false);
      unavailable = false;
    } on ApiException {
      events = const [];
      unavailable = true;
    }
    loading = false;
    notifyListeners();
  }
}
