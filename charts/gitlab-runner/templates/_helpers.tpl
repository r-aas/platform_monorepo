{{- define "gitlab-runner.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "gitlab-runner.labels" -}}
app.kubernetes.io/name: gitlab-runner
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "gitlab-runner.selectorLabels" -}}
app.kubernetes.io/name: gitlab-runner
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
