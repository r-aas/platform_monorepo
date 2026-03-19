{{/*
n8n ingress hostname: n8n.{namespace}.127.0.0.1.nip.io
*/}}
{{- define "n8n-standalone.host" -}}
n8n.{{ .Release.Namespace }}.127.0.0.1.nip.io
{{- end -}}
