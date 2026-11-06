FROM maven:3.9.9-eclipse-temurin-21 AS build
WORKDIR /build
COPY backend-java/pom.xml .
COPY backend-java/src src
RUN mvn -q package -DskipTests
FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=build /build/target/signalhub-0.1.0.jar app.jar
USER 10001
ENTRYPOINT ["java","-Xms64m","-Xmx384m","-jar","app.jar"]
