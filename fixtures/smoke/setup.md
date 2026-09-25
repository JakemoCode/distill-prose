# Setting up the local development environment

Welcome to the setup guide! In this document, we will walk you through everything you need to know in order to get your local development environment up and running. It is important to note that following these steps carefully will save you a great deal of time and frustration down the road. We have tried to make this process as smooth and painless as possible for everyone on the team.

## Overview

Before we dive in, let's take a moment to understand what we are going to accomplish. By the end of this guide, you will have a fully working copy of the application running on your own machine. This will allow you to make changes, test them, and see the results immediately. Having a local environment is a crucial part of the development workflow, and it enables you to iterate quickly and confidently.

## Prerequisites

First and foremost, you will need to make sure that you have the right tools installed on your computer. Specifically, you will need Node.js version 20 or later. You will also need PostgreSQL version 15, because the application stores all of its data in a Postgres database. Additionally, you will need to have Git installed so that you can clone the repository. If you do not already have these tools, please take the time to install them now before continuing with the rest of this guide.

## Getting the code

The next step in the process is to get a copy of the source code onto your machine. To do this, you will want to clone the repository from GitHub. Open up your terminal and run the clone command, which will download the entire codebase to a folder on your computer. Once the clone has finished, change into the new directory so that you are ready for the next step.

## Configuring the environment

Now that you have the code, you need to configure it. The application reads its configuration from a file called .env in the root of the project. There is an example file called .env.example that you can copy as a starting point. Copy it to .env and then open it in your editor. You must set DATABASE_URL to point at your local Postgres database, and you must set SESSION_SECRET to a random string that is at least 32 characters long. The application will refuse to start if SESSION_SECRET is shorter than 32 characters, so please be careful with this one.

## Running the application

Once everything is configured, you are finally ready to run the application! First run npm install to install all of the dependencies. Then run npm run migrate to set up the database tables. Finally, run npm run dev to start the development server. The server will start on port 3000, and you can open http://localhost:3000 in your browser to see the application running.

## Conclusion

Congratulations! You have now successfully set up your local development environment. As you can see, the process is fairly straightforward once you know the steps. To summarize, you installed the prerequisites, cloned the code, configured your environment, and started the application. If you run into any problems along the way, don't hesitate to reach out to the team for help. Happy coding!
