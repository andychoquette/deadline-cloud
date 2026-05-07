import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as elbv2 from "aws-cdk-lib/aws-elasticloadbalancingv2";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as ecr from "aws-cdk-lib/aws-ecr";
import * as apigwv2 from "aws-cdk-lib/aws-apigatewayv2";
import * as apigwv2_integrations from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { Construct } from "constructs";

export interface McpServerStackProps extends cdk.StackProps {
  readonly stage: string;
}

export class McpServerStack extends cdk.Stack {
  public readonly httpApi: apigwv2.HttpApi;
  public readonly service: ecs.FargateService;

  constructor(scope: Construct, id: string, props: McpServerStackProps) {
    super(scope, id, props);

    const { stage } = props;

    // --- Networking ---
    const vpc = new ec2.Vpc(this, "McpVpc", {
      maxAzs: 2,
      natGateways: 1,
      subnetConfiguration: [
        {
          name: "Public",
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS,
          cidrMask: 24,
        },
      ],
    });

    // --- ECR Repository ---
    const ecrRepo = new ecr.Repository(this, "McpServerRepo", {
      repositoryName: `deadline-mcp-server-${stage}`,
      removalPolicy:
        stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
      lifecycleRules: [
        {
          maxImageCount: 10,
          description: "Keep last 10 images",
        },
      ],
    });

    // --- ECS Cluster ---
    const cluster = new ecs.Cluster(this, "McpCluster", {
      vpc,
      containerInsights: true,
      clusterName: `deadline-mcp-${stage}`,
    });

    // --- Task Role (what the container can do) ---
    const taskRole = new iam.Role(this, "McpTaskRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      description:
        "Role assumed by the MCP server container. Only allows STS AssumeRoleWithWebIdentity for per-user credential delegation.",
    });

    // The task role can assume user delegation roles via web identity tokens.
    // The actual Deadline Cloud permissions come from the delegated role, not this one.
    taskRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
        resources: [
          `arn:aws:iam::${this.account}:role/DeadlineMcpUserDelegation`,
        ],
      })
    );

    // --- Task Execution Role (what ECS needs to launch the container) ---
    const executionRole = new iam.Role(this, "McpExecutionRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName(
          "service-role/AmazonECSTaskExecutionRolePolicy"
        ),
      ],
    });

    ecrRepo.grantPull(executionRole);

    // --- Log Group ---
    const logGroup = new logs.LogGroup(this, "McpServerLogs", {
      logGroupName: `/deadline/mcp-server/${stage}`,
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy:
        stage === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
    });

    // --- Task Definition ---
    const taskDef = new ecs.FargateTaskDefinition(this, "McpTaskDef", {
      cpu: 512,
      memoryLimitMiB: 1024,
      taskRole,
      executionRole,
    });

    taskDef.addContainer("mcp-server", {
      image: ecs.ContainerImage.fromEcrRepository(ecrRepo, "latest"),
      portMappings: [{ containerPort: 8000, protocol: ecs.Protocol.TCP }],
      environment: {
        MCP_AUTH_MODE: "oauth-delegation",
        MCP_TRANSPORT: "streamable-http",
        MCP_PORT: "8000",
        STAGE: stage,
      },
      logging: ecs.LogDrivers.awsLogs({
        logGroup,
        streamPrefix: "mcp",
      }),
      healthCheck: {
        command: [
          "CMD-SHELL",
          "python -c \"import socket; s=socket.socket(); s.connect(('127.0.0.1',8000)); s.close()\" || exit 1",
        ],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(5),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
    });

    // --- Fargate Service ---
    const serviceSg = new ec2.SecurityGroup(this, "McpServiceSg", {
      vpc,
      description: "MCP Server Fargate service",
      allowAllOutbound: true,
    });

    this.service = new ecs.FargateService(this, "McpService", {
      cluster,
      taskDefinition: taskDef,
      // Start with 0 on initial deploy (no image yet). Scale up after first image push.
      desiredCount: 0,
      assignPublicIp: false,
      securityGroups: [serviceSg],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      circuitBreaker: { rollback: true },
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
    });

    // --- Application Load Balancer ---
    const alb = new elbv2.ApplicationLoadBalancer(this, "McpAlb", {
      vpc,
      internetFacing: false,
      securityGroup: new ec2.SecurityGroup(this, "McpAlbSg", {
        vpc,
        description: "MCP Server ALB",
        allowAllOutbound: true,
      }),
    });

    const listener = alb.addListener("McpListener", {
      port: 80,
      protocol: elbv2.ApplicationProtocol.HTTP,
    });

    listener.addTargets("McpTargets", {
      port: 8000,
      targets: [this.service],
      healthCheck: {
        path: "/mcp",
        interval: cdk.Duration.seconds(30),
        healthyThresholdCount: 2,
        unhealthyThresholdCount: 3,
        healthyHttpCodes: "200,401,405,406",
      },
      deregistrationDelay: cdk.Duration.seconds(30),
    });

    // Allow ALB to reach the service
    serviceSg.addIngressRule(
      alb.connections.securityGroups[0],
      ec2.Port.tcp(8000),
      "Allow ALB to reach MCP server"
    );

    // --- API Gateway HTTP API ---
    this.httpApi = new apigwv2.HttpApi(this, "McpHttpApi", {
      apiName: `deadline-mcp-${stage}`,
      description: "Deadline Cloud MCP Server - streamable HTTP endpoint",
      corsPreflight: {
        allowOrigins: ["*"],
        allowMethods: [apigwv2.CorsHttpMethod.POST, apigwv2.CorsHttpMethod.GET],
        allowHeaders: ["Authorization", "Content-Type"],
      },
    });

    // VPC Link for private ALB integration
    const vpcLink = new apigwv2.VpcLink(this, "McpVpcLink", {
      vpc,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [serviceSg],
    });

    // Route all MCP traffic to the ALB
    this.httpApi.addRoutes({
      path: "/mcp",
      methods: [apigwv2.HttpMethod.POST, apigwv2.HttpMethod.GET],
      integration: new apigwv2_integrations.HttpAlbIntegration(
        "McpAlbIntegration",
        listener,
        { vpcLink }
      ),
    });

    // OAuth routes (authorize, token, callback, register, metadata)
    // FastMCP serves these under the root when auth is configured
    this.httpApi.addRoutes({
      path: "/{proxy+}",
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST],
      integration: new apigwv2_integrations.HttpAlbIntegration(
        "CatchAllIntegration",
        listener,
        { vpcLink }
      ),
    });

    // --- Auto Scaling ---
    const scaling = this.service.autoScaleTaskCount({
      minCapacity: stage === "prod" ? 2 : 1,
      maxCapacity: stage === "prod" ? 10 : 3,
    });

    scaling.scaleOnCpuUtilization("ScaleOnCpu", {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(30),
    });

    // --- IAM: User Delegation Role ---
    // This role is assumed per-request using the user's IdC OIDC token.
    // Trust policy allows AssumeRoleWithWebIdentity from the IdC issuer.
    const delegationRole = new iam.Role(this, "UserDelegationRole", {
      roleName: "DeadlineMcpUserDelegation",
      assumedBy: new iam.WebIdentityPrincipal(
        // The OIDC provider ARN — created separately or via custom resource
        // Placeholder: replace with actual IdC OIDC provider ARN
        `arn:aws:iam::${this.account}:oidc-provider/identitycenter.amazonaws.com`
      ),
      description:
        "Assumed by the MCP server on behalf of authenticated users. Grants Deadline Cloud read/write access scoped by the Deadline Cloud API's own IAM authorization.",
      maxSessionDuration: cdk.Duration.hours(1),
    });

    // Grant Deadline Cloud API access
    // The Frontdoor's IAM authorizer further scopes access per-user based on farm membership
    delegationRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
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
        resources: ["*"],
      })
    );

    // CloudWatch Logs access for session/worker logs
    delegationRole.addToPolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ["logs:GetLogEvents", "logs:FilterLogEvents"],
        resources: [`arn:aws:logs:*:*:log-group:/aws/deadline/*`],
      })
    );

    // --- Outputs ---
    new cdk.CfnOutput(this, "McpApiEndpoint", {
      value: this.httpApi.apiEndpoint,
      description: "MCP Server API Gateway endpoint URL",
    });

    new cdk.CfnOutput(this, "McpEcrRepoUri", {
      value: ecrRepo.repositoryUri,
      description: "ECR repository URI for MCP server images",
    });

    new cdk.CfnOutput(this, "McpClientConfig", {
      value: JSON.stringify({
        mcpServers: {
          "deadline-cloud": {
            url: `${this.httpApi.apiEndpoint}/mcp`,
          },
        },
      }),
      description: "MCP client configuration for connecting to this server",
    });
  }
}
