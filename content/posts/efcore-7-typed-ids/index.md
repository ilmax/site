---
title: "EF Core 7 is here - Welcome typed entity id 🍾"
date: 2022-11-17T13:09:55Z
draft: false
tags: ["ef-core", "dotnet", "ddd", "sql"]
---

[Source code](https://github.com/ilmax/EfCoreTypedId)

EF 7 has been released at [dotnetconf](https://www.dotnetconf.net/) and it brings a heap of new and exciting features. To read about all the new goodnes in this release you can go through the [What's new in EF Core 7](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-7.0/whatsnew) docs page.

One of the feature I'm more excited about that hasn't been properly advertised (hence this post), in my opinion, is support for what they call [Value generation for DDD guarded types](https://learn.microsoft.com/en-us/ef/core/what-is-new/ef-core-7.0/whatsnew#value-generation-for-ddd-guarded-types).

This neat new feature allow us to create custom types that wrap identifiers and supports value generation on the database side.

> You could already do this in the past if you were providing a value yourself, but it was not supported to generate the value on the database.

The feature is also negatively advertised with a warning on the EF Core docs page saying that it adds complexity to the code so let's find out what's this about and what it allow us to do.

## What's primitive obsessions?
>If you're a seasoned DDD practitioner you're probably familiar with this concept and you can skip this section altogether, if that's not the case keep reading.

Primitive obsession is a code smell and it's been defined as follows on hackernoon:

>Primitive Obsession is a code smell in which primitive data types are used excessively to represent your data models.

What this means is that we fail to properly model some domain concepts and we instead use more permissive primitive data types.

Sometimes using a more permissive type is a tradeoff forced by the limitations of the tools we use in our applications.

With EF Core we were limited in how to model the entity primary key with the value to be generated by the database.
If we wanted to use a sequence in the db to generate a monotonically increasing number for our entity id, we had to use an `int` as the primary key property type.

As an example let's use the following model used in most of the EF Core samples:

```csharp
public class Blog
{
    public int Id { get; private set; }
    public string Name { get; set; }
    public List<Post> Posts { get; } = new();
}

public class Post
{
    public int Id { get; private set; }
    public string Title { get; set; }
    public string Content { get; set; }
    public DateTime PublishedOn { get; set; }
}
```

As you can see, both **Blog** and **Post** entities have an `int` primary key.

This allows one subtle mistake not to be caught by the compiler: We can erroneously use the `Blog.Id` value in places where we should use the `Post.Id` or viceversa because both types are `int` and satisfies the type system requirements event though they're conceptually two completely different things.
Using the same type to represent different things besides opting out of compiler help, also hinders readability.

## DDD typed id to the rescue
Now with EF Core 7 we can easily avoid this problem defining two different types to represent the primary key of each entity and thanks to the C# feature `record struct` we can even get away with it with similar performance characteristics. 

Let's see it in action in the new model:

```csharp
public class Blog
{
    private Blog(BlogId id, string name)
    {
        Id = id;
        Name = name;
    }

    public BlogId Id { get; private set; }

    public string Name { get; set; }

    public List<Post> Posts { get; private set; } = new();

    public static Blog Create(string name)
    {
        if (name == null)
        {
            throw new ArgumentNullException(nameof(name));
        }

        return new Blog(default, name);
    }
}

public record struct BlogId(int Value);

public class Post
{
    private Post(PostId id, string title, string content, DateTimeOffset publishedOn)
    {
        Id = id;
        Title = title;
        Content = content;
        PublishedOn = publishedOn;
    }

    public PostId Id { get; private set; }
    public string Title { get; set; }
    public string Content { get; set; }
    public DateTimeOffset PublishedOn { get; set; }

    public static Post Create(string title, string content)
    {
        if (title == null)
        {
            throw new ArgumentNullException(nameof(title));
        }

        if (content == null)
        {
            throw new ArgumentNullException(nameof(content));
        }

        return new Post(default, title, content, DateTimeOffset.UtcNow);
    }
}

public record struct PostId(int Value);
```
In order for EF Core to understand how to map the two new types PostId and BlogId to the dB, we need to use value converters like the following:

```csharp
public class BlogIdIdConverter : ValueConverter<BlogId, int>
{
    public BlogIdIdConverter()
        : base(v => v.Value, v => new(v))
    { }
}
public class PostIdIdConverter : ValueConverter<PostId, int>
{
    public PostIdIdConverter()
        : base(v => v.Value, v => new(v))
    { }
}

// register value converters, we can take advantage of the new model building conventions feature and register the value converters only once for our whole context 

protected override void ConfigureConventions(ModelConfigurationBuilder configurationBuilder)
{
    configurationBuilder.Properties<BlogId>().HaveConversion<BlogIdIdConverter>();
    configurationBuilder.Properties<PostId>().HaveConversion<PostIdIdConverter>();
}

// Last step is to configure the value generation for these entity keys in the OnModelCreating method

modelBuilder.Entity<Blog>().Property(blog => blog.Id).ValueGeneratedOnAdd();
modelBuilder.Entity<Post>().Property(post => post.Id).ValueGeneratedOnAdd();

```

Implementing the entity ids this way allow use to fix the aforementioned problem since now the two types are different so we're unable to pass a `Blog.Id` where we expect a `Post.Id` or vice versa.
This may seems like a small feature, but if you search the web, there're tons of articles that describe why this is useful (i.e. more expressive code, compile support, easier refactoring, etc).

## Put it all together

Let's see how this work:
```csharp
var blog = Blog.Create("My First Blog!");
context.Add(blog);
context.SaveChanges();
```
The code above produces the following Sql:
```sql
SET IMPLICIT_TRANSACTIONS OFF;
SET NOCOUNT ON;
INSERT INTO [Blogs] ([Name])
OUTPUT INSERTED.[Id]
VALUES (@p0);
```

>Note that since this is only inserting one value and the database already guarantees atomicity for a single insert, the statement is not wrapped into a transaction, one of the nice performance benefits that we will get for free just updating to EF Core 7.

Now, add few posts:
```csharp
blog.Posts.Add(Post.Create("First post", "EF Core is awesome"));
blog.Posts.Add(Post.Create("Second post", "Typed Ids are amazing"));
context.SaveChanges();
```
Produces the following Sql:
```sql
SET IMPLICIT_TRANSACTIONS OFF;
SET NOCOUNT ON;
MERGE [Post] USING (
VALUES (@p0, @p1, @p2, @p3, 0),
(@p4, @p5, @p6, @p7, 1)) AS i ([BlogId], [Content], [PublishedOn], [Title], _Position) ON 1=0
WHEN NOT MATCHED THEN
INSERT ([BlogId], [Content], [PublishedOn], [Title])
VALUES (i.[BlogId], i.[Content], i.[PublishedOn], i.[Title])
OUTPUT INSERTED.[Id], i._Position; 
```

And now the reading part, reading a blog from the db:
```csharp
BlogId id = blog.Id;
var blogFromDb = context.Blogs.SingleOrDefault(blog => blog.Id == id);
```

Produces the expected sql:
```sql
SELECT TOP(2) [b].[Id], [b].[Name]
FROM [Blogs] AS [b]
WHERE [b].[Id] = @__id_0
```

As you can see everything works smoothly as you'd expect and with little more code, you also have some additional type safety that comes in handy especially at refactoring time, and if you, by mistake, use a `Post.Id` where a `Blog.Id` is expected, you get a nice compiler error.

## Caveats
I implemented the `BlogId` and `PostId` using records to keep the code succinct, in real life you may want to add a bit more to it, like for example overriding ToString to only print value, and maybe add some validation to make sure you can't create a negative value and so on, using a struct also has some similar performance characteristics of using an `int`.

Please also note that EF Core 7 has few issues that will be resolved in the coming months so you may want to wait for some of these issues to be resolved before pushing it to prod.
{{< twitter 1593244935939305474 >}} 

I hope you enjoyed this article, till the next time!