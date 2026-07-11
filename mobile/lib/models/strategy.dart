// DTO for GET /api/strategies (strategy-engine StrategySummary).

class StrategySummary {
  const StrategySummary({
    required this.key,
    required this.name,
    required this.version,
    required this.category,
    required this.markets,
    required this.timeframes,
    required this.enabled,
    required this.description,
  });

  factory StrategySummary.fromJson(Map<String, dynamic> json) => StrategySummary(
        key: json['key'] as String? ?? '',
        name: json['name'] as String? ?? '',
        version: json['version'] as String? ?? '',
        category: json['category'] as String? ?? '',
        markets: (json['markets'] as List<dynamic>? ?? const [])
            .map((m) => m.toString())
            .toList(growable: false),
        timeframes: (json['timeframes'] as List<dynamic>? ?? const [])
            .map((t) => t.toString())
            .toList(growable: false),
        enabled: json['enabled'] as bool? ?? true,
        description: json['description'] as String? ?? '',
      );

  final String key;
  final String name;
  final String version;
  final String category;
  final List<String> markets;
  final List<String> timeframes;
  final bool enabled;
  final String description;

  StrategySummary copyWith({bool? enabled}) => StrategySummary(
        key: key,
        name: name,
        version: version,
        category: category,
        markets: markets,
        timeframes: timeframes,
        enabled: enabled ?? this.enabled,
        description: description,
      );
}
