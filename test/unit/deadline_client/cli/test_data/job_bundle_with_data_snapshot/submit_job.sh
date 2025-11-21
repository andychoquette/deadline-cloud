#!/bin/sh
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
set -xeuo pipefail
cd "$(dirname "$0")"

aws s3 cp \
    --recursive \
    ./Data \
    s3://deadline-job-attachments-mock-bucket/MockRootPrefix/Data

aws s3 cp \
    --recursive \
    ./Manifests \
    s3://deadline-job-attachments-mock-bucket/MockRootPrefix/Manifests

aws deadline create-job \
    --farm-id farm-test123 \
    --queue-id queue-test456 \
    --template file://template_param.data \
    --template-type YAML \
    --priority 50 \
    --attachments file://attachments_param.json \
    --parameters file://parameters_param.json
