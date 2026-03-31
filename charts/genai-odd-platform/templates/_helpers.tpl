{{- define "genai-odd-platform.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "genai-odd-platform.labels" -}}
app.kubernetes.io/name: odd-platform
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "genai-odd-platform.selectorLabels" -}}
app.kubernetes.io/name: odd-platform
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
