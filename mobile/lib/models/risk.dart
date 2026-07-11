// DTOs for risk-engine responses: circuit breaker status and risk events
// (the events list endpoint is not live yet; the alerts screen degrades to
// an empty state until it lands).

class CircuitBreakerStatus {
  const CircuitBreakerStatus({
    required this.state,
    this.reason,
    this.errorCount = 0,
  });

  factory CircuitBreakerStatus.fromJson(Map<String, dynamic> json) =>
      CircuitBreakerStatus(
        state: json['state'] as String? ?? 'UNKNOWN',
        reason: json['reason'] as String?,
        errorCount: json['error_count'] as int? ?? 0,
      );

  final String state;
  final String? reason;
  final int errorCount;

  bool get isNormal => state.toUpperCase() == 'NORMAL';
}

class RiskEvent {
  const RiskEvent({
    required this.id,
    required this.eventType,
    this.signalId,
    this.payload = const {},
    this.createdAt,
  });

  factory RiskEvent.fromJson(Map<String, dynamic> json) => RiskEvent(
        id: json['id'] as String? ?? '',
        eventType: json['event_type'] as String? ?? '',
        signalId: json['signal_id'] as String?,
        payload: json['payload'] as Map<String, dynamic>? ?? const {},
        createdAt: json['created_at'] as String?,
      );

  final String id;
  final String eventType;
  final String? signalId;
  final Map<String, dynamic> payload;
  final String? createdAt;
}
