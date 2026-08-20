{{/* Chart name (optionally overridden). */}}
{{- define "observai.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully qualified release name, used as the prefix for every resource. */}}
{{- define "observai.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "observai.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Per-component resource names. Both the Service definitions and the URLs
     that reference them use these, so cross-service wiring can never drift. */}}
{{- define "observai.gateway.fullname" -}}{{- printf "%s-gateway" (include "observai.fullname" .) -}}{{- end -}}
{{- define "observai.inference.fullname" -}}{{- printf "%s-inference" (include "observai.fullname" .) -}}{{- end -}}
{{- define "observai.collector.fullname" -}}{{- printf "%s-collector" (include "observai.fullname" .) -}}{{- end -}}
{{- define "observai.redis.fullname" -}}{{- printf "%s-redis" (include "observai.fullname" .) -}}{{- end -}}
{{- define "observai.ollama.fullname" -}}{{- printf "%s-ollama" (include "observai.fullname" .) -}}{{- end -}}
{{- define "observai.loadgen.fullname" -}}{{- printf "%s-loadgen" (include "observai.fullname" .) -}}{{- end -}}

{{/* Name of the Secret holding the Dynatrace endpoint + token. */}}
{{- define "observai.dynatrace.secretName" -}}
{{- if .Values.dynatrace.existingSecret -}}
{{- .Values.dynatrace.existingSecret -}}
{{- else -}}
{{- printf "%s-dynatrace" (include "observai.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Labels applied to every object (never used in selectors). */}}
{{- define "observai.commonLabels" -}}
helm.sh/chart: {{ include "observai.chart" . }}
app.kubernetes.io/part-of: observai
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}
