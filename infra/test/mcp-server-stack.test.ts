import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { McpServerStack } from "../lib/mcp-server-stack";

describe("McpServerStack", () => {
  const app = new cdk.App();
  const stack = new McpServerStack(app, "TestStack", {
    stage: "dev",
    env: { account: "123456789012", region: "us-west-2" },
  });
  const template = Template.fromStack(stack);

  test("creates ECS cluster", () => {
    template.resourceCountIs("AWS::ECS::Cluster", 1);
  });

  test("creates Fargate service", () => {
    template.resourceCountIs("AWS::ECS::Service", 1);
  });

  test("creates ALB", () => {
    template.resourceCountIs(
      "AWS::ElasticLoadBalancingV2::LoadBalancer",
      1
    );
  });

  test("creates HTTP API Gateway", () => {
    template.resourceCountIs("AWS::ApiGatewayV2::Api", 1);
  });

  test("creates VPC with private subnets", () => {
    template.resourceCountIs("AWS::EC2::VPC", 1);
    template.hasResourceProperties("AWS::EC2::Subnet", {
      MapPublicIpOnLaunch: false,
    });
  });

  test("creates user delegation IAM role", () => {
    template.hasResourceProperties("AWS::IAM::Role", {
      RoleName: "DeadlineMcpUserDelegation",
    });
  });

  test("delegation role has Deadline Cloud permissions", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: [
          {
            Action: [
              "deadline:GetJob",
              "deadline:ListJobs",
              "deadline:ListFarms",
              "deadline:ListQueues",
              "deadline:ListFleets",
              "deadline:ListSessions",
              "deadline:ListSteps",
              "deadline:ListTasks",
              "deadline:SearchJobs",
              "deadline:GetSession",
              "deadline:ListStorageProfilesForQueue",
              "deadline:CreateJob",
            ],
            Effect: "Allow",
            Resource: "*",
          },
        ],
      },
    });
  });

  test("ECR repository has lifecycle rules", () => {
    template.hasResourceProperties("AWS::ECR::Repository", {
      LifecyclePolicy: {
        LifecyclePolicyText: JSON.stringify({
          rules: [
            {
              rulePriority: 1,
              description: "Keep last 10 images",
              selection: {
                tagStatus: "any",
                countType: "imageCountMoreThan",
                countNumber: 10,
              },
              action: { type: "expire" },
            },
          ],
        }),
      },
    });
  });

  test("task role can only assume delegation role via web identity", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: [
          {
            Action: ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
            Effect: "Allow",
            Resource:
              "arn:aws:iam::123456789012:role/DeadlineMcpUserDelegation",
          },
        ],
      },
    });
  });

  describe("prod stage", () => {
    const prodApp = new cdk.App();
    const prodStack = new McpServerStack(prodApp, "ProdStack", {
      stage: "prod",
      env: { account: "123456789012", region: "us-west-2" },
    });
    const prodTemplate = Template.fromStack(prodStack);

    test("prod has desired count of 2", () => {
      prodTemplate.hasResourceProperties("AWS::ECS::Service", {
        DesiredCount: 2,
      });
    });
  });
});
