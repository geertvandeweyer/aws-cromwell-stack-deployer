#!/usr/bin/env bash
set -Eeuo pipefail

exec >> /var/log/cromwell/server.log 2>&1
cd /opt/cromwell

if [[ -n "$CROMWELL_DB_SECRET_ARN" ]]; then
  export CROMWELL_DB_SECRET_JSON="$(aws secretsmanager get-secret-value \
    --secret-id "$CROMWELL_DB_SECRET_ARN" \
    --query SecretString --output text --region "$AWS_REGION")"
else
  export CROMWELL_DB_SECRET_JSON='{}'
fi

python3 - <<'PY'
import json
import os
from pathlib import Path


def hocon(value: str) -> str:
    return json.dumps(value)

secret = json.loads(os.environ.get("CROMWELL_DB_SECRET_JSON", "{}"))
queue = hocon(os.environ["CROMWELL_DEFAULT_QUEUE_ARN"])
region = hocon(os.environ["AWS_REGION"])
script_bucket = hocon(os.environ["CROMWELL_SCRIPT_BUCKET"])
working_disk_size = os.environ.get("CROMWELL_WORKING_DISK_SIZE_GB", "")
working_disk = hocon(
  f"local-disk {working_disk_size} SSD" if working_disk_size else "local-disk"
)
root = hocon(f"s3://{os.environ['CROMWELL_ROOT_BUCKET']}/cromwell-execution")
database_config = ""
if os.environ.get("CROMWELL_DB_HOST"):
    database_config = f'''database {{
  profile = "slick.jdbc.MySQLProfile$"
  db {{
    driver = "com.mysql.cj.jdbc.Driver"
    url = "jdbc:mysql://{os.environ['CROMWELL_DB_HOST']}:3306/cromwell?rewriteBatchedStatements=true&serverTimezone=UTC&sslMode=REQUIRED"
    user = {hocon(secret.get('username', ''))}
    password = {hocon(secret.get('password', ''))}
    connectionTimeout = 5000
  }}
}}'''
config = f'''include required(classpath("application"))

aws {{
  application-name = "cromwell"
  region = {region}
  auths = [{{ name = "default", scheme = "default" }}]
}}

engine.filesystems.s3.auth = "default"

{database_config}

backend {{
  default = "AWSBatch"
  providers {{
    AWSBatch {{
      actor-factory = "cromwell.backend.impl.aws.AwsBatchBackendLifecycleActorFactory"
      config {{
        auth = "default"
        root = {root}
        numSubmitAttempts = 6
        numCreateDefinitionAttempts = 6
        default-runtime-attributes {{
          queueArn = {queue}
          scriptBucketName = {script_bucket}
          disks = {working_disk}
        }}
        runtime-attributes {{
          queueArn = {queue}
          scriptBucketName = {script_bucket}
          disks = {working_disk}
        }}
        filesystems.s3.auth = "default"
      }}
    }}
  }}
}}
'''
Path("/opt/cromwell/application.conf").write_text(config, encoding="utf-8")
PY
unset CROMWELL_DB_SECRET_JSON
exec java -Dconfig.file=/opt/cromwell/application.conf -jar /opt/cromwell/cromwell.jar server
