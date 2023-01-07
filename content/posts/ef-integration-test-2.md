---
title: "Integration testing with EF Core, part 2"
date: 2021-04-06T16:25:33Z
draft: false
tags: ["efcore", "testing", "dotnet", "docker"]
---

In the [first part](https://dev.to/maxx_don/integration-testing-with-ef-core-part-1-1l40) of this mini series, I described how I implemented integration tests with EF core and SQL Server running on top of a Docker container. The approach explained in the first blog post works but it has one very big downside, the ability to debug integration tests.

In order to be able to do so, we need to replace Docker compose with a code based solution and, depending on your testing framework of choice, pick the appropriate hook to start the SQL Server container.

To run Docker in C# we can just start a new [Process](https://docs.microsoft.com/en-us/dotnet/api/system.diagnostics.process?view=net-5.0), configure all arguments, handle it's lifecycle and so on or, since this looks like quite some work, pick a library that already wraps Docker and exposes it in C#. 
I knew Java had [Testcontainers](https://www.testcontainers.org/) that's marketed as:
>Testcontainers is a Java library that supports JUnit tests, providing lightweight, throwaway instances of common databases, Selenium web browsers, or anything else that can run in a Docker container.

This is exactly what we need, so I went to look for the *dotnet* counterpart and sure enough I found [Dotnet.Testcontainers](https://github.com/HofmeisterAn/dotnet-testcontainers) and decided to give it a try.

Depending on the test framework you use, you have to find the proper hook to tell testcontainers to start your SQL Server Docker container just before test execution starts. I am using [NUnit](https://nunit.org/) so the hook I picked is a class in the root namespace of the integration test project with the `[SetupFixture]` attribute applied to it.

>you can also have the class outside of every namespace, for more info see [here](https://www.automatetheplanet.com/nunit-cheat-sheet/)

If you are using [xUnit.net](https://xunit.net), you can probably achieve the same via a [collection fixture](https://xunit.net/docs/shared-context#collection-fixture), if you're on MSTest V2, you can probably use the `[AssemblyInitialize]` hook, you can find more info on [StackOverflow](https://stackoverflow.com/questions/1427443/global-test-initialize-method-for-mstest) 

[Dotnet.Testcontainers](https://github.com/HofmeisterAn/dotnet-testcontainers) also comes with some built-in classes that wraps various services, one of these classes actually wraps a SQL Server Docker container and there are few more that covers the most common databases e.g.
* MySql
* Oracle
* Postgres

and few more are available, to see the full list check [here](https://github.com/HofmeisterAn/dotnet-testcontainers/tree/master/src/DotNet.Testcontainers/Containers/Modules/Databases).

So after installing the nuget package `DotNet.Testcontainers`, I created a class like the following:

```csharp
[SetUpFixture]
public class TestFixture
{
    private MsSqlTestcontainer _container;

    [OneTimeSetUp]
    public async Task GlobalSetup()
    {
        var builder = new TestcontainersBuilder<MsSqlTestcontainer>()
            .WithName("sql-server-db")
            .WithDatabase(new MsSqlTestcontainerConfiguration("mcr.microsoft.com/mssql/server:2019-latest")
            {
                Password = "Guess_me",
                Port = 1535
            });

        _container = builder.Build();
        await _container.StartAsync();

        // Access the connection string via _container.ConnectionString
    }

    [OneTimeTearDown]
    public async Task GlobalTeardown()
    {
        await _container.StopAsync();
    }
}
```
With this class in place, I was able to start a container before running the first test method, the only problem I was left with was clean-up. What happens if something during test execution prevents the code to properly tear down the container? This error typically manifest itself with an exception at startup, there can be several reasons this may happen e.g. using a duplicate container name name or use a port that's already in use on the host machine.
To cope with this limitation I could wrap the startup in a try catch statement but I wasn’t very happy with the result, so I decided to come up with a tiny [PR](https://github.com/HofmeisterAn/dotnet-testcontainers/pull/360) to allow override the `StartAsync` method in a class that derives from [TestcontainersContainer](https://github.com/HofmeisterAn/dotnet-testcontainers/blob/develop/src/DotNet.Testcontainers/Containers/Modules/TestcontainersContainer.cs), the class that wraps the actual container lifecycle, so we can derive from it and override the `StartAsync` method to implement our custom start-up logic.

>Unfortunately we cannot derive from the built-in `MsSqlTestcontainer` class since it's sealed as you can see [here](https://github.com/HofmeisterAn/dotnet-testcontainers/blob/master/src/DotNet.Testcontainers/Containers/Modules/Databases/MsSqlTestcontainer.cs)

The class may look as easy as this:

```csharp
public sealed class SqlServerTestcontainer : TestcontainerDatabase
{
    internal SqlServerTestcontainer(ITestcontainersConfiguration configuration)
        : base(configuration)
    { }

    public override string ConnectionString => $"Server=127.0.0.1,{Port};Database={Database};User Id={Username};Password={Password};";

    public override async Task StartAsync(CancellationToken cancellationToken = default)
    {
        bool retry = true;
        while (true)
        {
            try
            {
                await base.StartAsync(cancellationToken);
                break;
            }
            catch (DockerApiException dockerApiException) when (retry && dockerApiException.StatusCode == HttpStatusCode.Conflict)
            {
                retry = false;
                await NukeItAsync("sql-server-db");
            }
        }
    }

    private async Task NukeItAsync(string name)
    {
        var uri = RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? new Uri("npipe://./pipe/docker_engine") : new Uri("unix:/var/run/docker.sock");
        var dockerClient = new DockerClientConfiguration(uri).CreateClient();

        // Stop the container if it's running and remove it
        await dockerClient.Containers.RemoveContainerAsync(name, new ContainerRemoveParameters { Force = true });
    }
}
```

As you can see in the `StartAsync` method, I'm catching the exception thrown if the container already exists, nuke it and retry starting the container again.

This could be handled better by the tescontainers library itself and there's an actual issue tracking the improvement [here](https://github.com/HofmeisterAn/dotnet-testcontainers/issues/242), but for the time being I can live with this, especially considering that this will allow me to debug integration tests within my IDE of choice.

>Starting the SQL Server container takes time, ~30 sec on my dev machine, so this will be the cost you have to pay before starting the tests execution.

This is the end of this mini series, I hope you enjoyed it and find it useful.