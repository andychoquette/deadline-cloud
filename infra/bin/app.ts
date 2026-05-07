#!/usr/bin/env node
import "source-map-support/register";
import * as cdk from "aws-cdk-lib";
import { McpServerStack } from "../lib/mcp-server-stack";

const app = new cdk.App();

const stage = app.node.tryGetContext("stage") || process.env.STAGE || "dev";
const account =
  app.node.tryGetContext("account") || process.env.CDK_DEFAULT_ACCOUNT;
const region =
  app.node.tryGetContext("region") || process.env.CDK_DEFAULT_REGION || "us-west-2";

new McpServerStack(app, `DeadlineMcpServer-${stage}`, {
  stage,
  env: { account, region },
  description: "Deadline Cloud remote MCP Server infrastructure",
});
