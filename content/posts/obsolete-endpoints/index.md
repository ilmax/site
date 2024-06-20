---
title: "Mastering Endpoint Evolution: Safely Retiring Obsolete APIs with ASP.NET Core, OpenTelemetry, and Aspire"
date: 2024-06-20T10:16:10+02:00
draft: true
tags: ["dotnet", "otel", "aspire"]
---

Have you ever found yourself deprecating endpoints and willing to clean them up after some time? Have you ever deleted obsolete endpoints only to discover, after the deployment that some forgotten service was still using those endpoints? Have you ever needed to track the usage of those obsolete endpoints to plot a nice roadmap toward safe deletion?

If those questions resonate with you, please follow along, I will show you how you can use [OpenTelemetry](https://opentelemetry.io/) to track usage metrics and [Aspire](https://learn.microsoft.com/en-us/dotnet/aspire/get-started/aspire-overview) to visualize those metrics.
As we all know, APIs tend to evolve and managing API versioning is a tricky business. More often than not we need to live with multiple versions of an API just because we are not sure if you can delete the older version of the API and you choose the "better safe than sorry" way of dealing with the problem.

## Obsoleting endpoints

In ASP.NET Core we can add attributes to our endpoints to mark them obsolete, you can roll your own or, preferably, use the built-in `[ObsoleteAttribute]` that will render the obsolete endpoints nicely as shown below

![Swagger UI obsolete endpoints](images/swagger-ui-obsolete-endpoints.png "Swagger UI obsolete endpoints")

> Please note that if you use `WithOpenApi()` on a minimal api, it doesn't show the endpoint as obsolete in the UI, refer to the [documentation](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/minimal-apis/openapi?view=aspnetcore-8.0) to correctly setup OpenApi in minimal api

If you're using controllers, you can add the `[Obsolete]` attribute to a controller action or you can apply the attribute to the whole controller as shown below:

```csharp
[Tags("Controller")]
[Route("api/[controller]")]
public class WeatherController : ControllerBase
{
    [HttpGet]
    [Obsolete]
    public IActionResult GetWeather()
    {
        return Ok(WeatherGenerator.Generate());
    }
}
```

If you're using Minimal API instead, you can achieve the same effect using the following code

```csharp
app.MapGet("/weatherforecast", [Obsolete]() => WeatherGenerator.Generate())
    .WithTags("MinimalApi");
```

> Minimal API is a simplified approach for building HTTP APIs in ASP.NET Core, if you want to know more, make sure you check-out the [documentation](https://learn.microsoft.com/en-us/aspnet/core/fundamentals/minimal-apis/overview?view=aspnetcore-8.0)

## Intercepting endpoint invocations

Now that we marked the endpoints as obsolete, we need to emit custom telemetry every time our endpoints. In the MVC world (i.e. when we build our API using controllers) we can implement a filter.
[Filters](https://learn.microsoft.com/en-us/aspnet/core/mvc/controllers/filters?view=aspnetcore-8.0) in MVC are a very powerful way of executing custom code in various stages of the HTTP request pipeline.

![MVC Filters](images/mvc-filters.png "MVC Filters")

*Image courtesy of [https://learn.microsoft.com/en-us/aspnet/core/mvc/controllers/filters?view=aspnetcore-8.0](https://learn.microsoft.com/en-us/aspnet/core/mvc/controllers/filters?view=aspnetcore-8.0)*

As you can see from the image above, the best option is to implement an ActionFilter that runs just before and after our controller action. The code is quite straightforward, we check if our action (the method in the controller that implements the HTTP API) has the obsolete attribute and we emit some telemetry as shown below:

```csharp
public class ObsoleteActionFilter : IAsyncActionFilter
{
    public async Task OnActionExecutionAsync(ActionExecutingContext context, ActionExecutionDelegate next)
    {
        var obsoleteAttribute = context.ActionDescriptor.EndpointMetadata.OfType<ObsoleteAttribute>().FirstOrDefault();
        if (obsoleteAttribute is not null)
        {
            // Emit custom telemetry
            await next();
        }
        else
        {
            await next();    
        }
    }
}
```

For Minimal API we have to implement something similar, but we can't reuse the same code, we have to instead craft a filter specifically for Minimal API like the following:

```csharp
public class ObsoleteEndpointFilter : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var endpoint = context.HttpContext.GetEndpoint();
        if (endpoint is not null)
        {
            var obsolete = endpoint.Metadata.OfType<ObsoleteAttribute>().FirstOrDefault();
            if (obsolete is not null)
            {
                // Emit custom telemetry
                return await next(context);
            }
        }

        return await next(context);
    }
}
```

## Emitting custom telemetry

Now that the skeleton of our filters is done, we have to emit custom telemetry to signal that an obsolete endpoint has been invoked. With OpenTelemetry we can emit a [metric signal](https://opentelemetry.io/docs/concepts/signals/metrics/)
In dotnet to emit custom telemetry we need to create a `Meter` and from the meter, we need to create an instrument, in our case the `Counter<T>` seems the most appropriate, so we will use that one, when you have a counter you can simply record the invocation.
>Showing how to best use OpenTelemetry is outside of the scope of this article, but if you're interested there's a great and very pragmatic [YoutTube video](https://www.youtube.com/watch?v=WzZI_IT6gYo&ab_channel=NDCConferences) on how to do telemetry in dotnet by [Martin Thwaites](https://x.com/MartinDotNet) that can get you up to speed quickly.

Please note that the `Meter` class needs to be a singleton and you should configure OpenTelemetry to listen to the specific meter using the same name to get telemetry emitted. Don't worry if this sounds a bit convoluted now, especially if you're not so familiar with how OpenTelemetry works in dotnet. Martin does an excellent job in getting you up to speed quickly and you can all find all the source code for this article in my GitHub repository [here](https://github.com/ilmax/obsolete-endpoints).

So without further ado, here's the OpentTelementry code:

```csharp
// Service level configuration
public static class DiagnosticConfig
{
    private const string ServiceName = "ObsoleteEndpointsService";
    public static readonly Meter Meter = new(ServiceName);
    public static readonly Counter<long> ObsoleteEndpointCounter = Meter.CreateCounter<long>("ObsoleteInvocationCount");
    public static readonly ActivitySource Source = new(ServiceName);
}

// Action Filter (MVC)
public class ObsoleteActionFilter : IAsyncActionFilter
{
    public async Task OnActionExecutionAsync(ActionExecutingContext context, ActionExecutionDelegate next)
    {
        var obsoleteAttribute = context.ActionDescriptor.EndpointMetadata.OfType<ObsoleteAttribute>().FirstOrDefault();
        if (obsoleteAttribute is not null)
        {
            // Emit custom trace
            using var activity = DiagnosticConfig.Source.StartActivity(DiagnosticNames.ObsoleteEndpointInvocation);
            activity.EnrichWithActionContext(context);

            // Emit custom metric
            DiagnosticConfig.ObsoleteEndpointCounter.Add(1, new KeyValuePair<string, object?>(DiagnosticNames.DisplayName, context.ActionDescriptor.DisplayName));
            await next();
        }
        else
        {
            await next();    
        }
    }
}

// Endpoint Filter (Minimal API)
public class ObsoleteEndpointFilter : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var endpoint = context.HttpContext.GetEndpoint();
        if (endpoint is not null)
        {
            var obsolete = endpoint.Metadata.OfType<ObsoleteAttribute>().FirstOrDefault();
            if (obsolete is not null)
            {
                // Emit custom trace
                using var activity = DiagnosticConfig.Source.StartActivity(DiagnosticNames.ObsoleteEndpointInvocation);
                activity.EnrichWithEndpoint(endpoint, context.HttpContext);

                // Emit custom metric
                DiagnosticConfig.ObsoleteEndpointCounter.Add(1, new KeyValuePair<string, object?>(DiagnosticNames.DisplayName, endpoint.DisplayName));
                return await next(context);
            }
        }

        return await next(context);
    }
}
```

## Register the filters

Now that we created filters, we need to register them. MVC and Minimal API have two different ways of registering a filter, in MVC you can do it in several ways, but if you want to apply the filter globally, you can do the following:

```csharp
builder.Services.AddControllers(opt =>
{
    opt.Filters.Add<ObsoleteActionFilter>();
});
```

Whilst in Minimal API there's no easy way to register a global endpoint filter so in my case I'm adding it to the single endpoint in this way:

```csharp
app.MapGet("/weatherforecast", [Obsolete]() => WeatherGenerator.Generate())
    .AddEndpointFilter<ObsoleteEndpointFilter>() // <-- Filter added here
    .WithTags("MinimalApi");
```

Actually, there are some clever tricks you can do to register a filter globally, [Khalid Abuhakmeh](https://github.com/khalidabuhakmeh) has written a nice post about it, you if you're interested you can find more [here](https://khalidabuhakmeh.com/global-endpoint-filters-with-aspnet-core-minimal-apis)

## Visualize the telemetry in Aspire

The metrics telemetry gets collected in Aspire and shown as follows:
![Obsolete metrics](images/metrics.png "Obsolete metrics")

As you can see I'm not adding many additional tags here, I'm just adding the display name that ASP.NET Core computes for the action/endpoint. This should be enough information to identify the called endpoint, but maybe you need some more information about the caller, to accomplish this I decided to also emit a custom span that I then enrich with the `ActionExecutingContext`/`EndpointFilterInvocationContext` with the following code:

```csharp
public static class ActivityExtensions
{
    public static void EnrichWithEndpoint(this Activity? activity, Endpoint endpoint, HttpContext httpContext)
    {
        activity?.SetTag(DiagnosticNames.Url, httpContext.Request.GetDisplayUrl());
        activity?.SetTag(DiagnosticNames.DisplayName, endpoint.DisplayName);
    }
    
    public static void EnrichWithActionContext(this Activity? activity, ActionExecutingContext context)
    {
        activity?.SetTag(DiagnosticNames.Url, context.HttpContext.Request.GetDisplayUrl());
        activity?.SetTag(DiagnosticNames.DisplayName, context.ActionDescriptor.DisplayName);
    }
}
```

This allows you to add all additional information your analysis will require.
>Please make sure that's quite easy to discose sensitive data in your APM of choice so beware of what tags you're adding to the span.

This is how the span will show in Aspire:
![Obsolete trace](images/traces.png "Obsolete trace")

## References

- [https://www.youtube.com/watch?v=WzZI_IT6gYo&ab_channel=NDCConferences](https://www.youtube.com/watch?v=WzZI_IT6gYo&ab_channel=NDCConferences)
- [https://khalidabuhakmeh.com/global-endpoint-filters-with-aspnet-core-minimal-apis](https://khalidabuhakmeh.com/global-endpoint-filters-with-aspnet-core-minimal-apis)
- [https://opentelemetry.io/docs/getting-started/dev/](https://opentelemetry.io/docs/getting-started/dev/)
- [https://learn.microsoft.com/en-us/dotnet/aspire/get-started/aspire-overview](https://learn.microsoft.com/en-us/dotnet/aspire/get-started/aspire-overview)

## Conclusions

I hope you found this post useful, till the next time
