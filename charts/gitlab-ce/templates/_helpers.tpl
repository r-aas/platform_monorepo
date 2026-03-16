{{/*
GitLab CE chart helpers
*/}}

{{- define "gitlab-ce.fullname" -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "gitlab-ce.labels" -}}
app.kubernetes.io/name: gitlab-ce
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{- define "gitlab-ce.selectorLabels" -}}
app.kubernetes.io/name: gitlab-ce
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "gitlab-ce.runner.labels" -}}
app.kubernetes.io/name: gitlab-runner
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: runner
{{- end }}

{{- define "gitlab-ce.runner.selectorLabels" -}}
app.kubernetes.io/name: gitlab-runner
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
