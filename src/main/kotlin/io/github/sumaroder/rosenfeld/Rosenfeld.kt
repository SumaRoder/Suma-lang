package io.github.sumaroder.rosenfeld

import io.github.sumaroder.rosenfeld.ast.Decl
import io.github.sumaroder.rosenfeld.ast.ImportDecl
import io.github.sumaroder.rosenfeld.ast.Program
import io.github.sumaroder.rosenfeld.interpreter.Interpreter
import io.github.sumaroder.rosenfeld.parse.Parser
import io.github.sumaroder.rosenfeld.tokenize.TokenInfo
import io.github.sumaroder.rosenfeld.tokenize.Tokenizer
import java.io.File

sealed class ModuleSource {
    abstract fun readContent(): String
    abstract fun getParentPath(): String?

    data class FileSource(val file: File) : ModuleSource() {
        override fun readContent(): String = file.readText()
        override fun getParentPath(): String? = file.parentFile?.absolutePath
    }

    data class ResourceSource(val path: String) : ModuleSource() {
        override fun readContent(): String {
            val stream = javaClass.getResourceAsStream(path)
                ?: throw IllegalArgumentException("Resource not found: $path")
            return stream.bufferedReader().use { it.readText() }
        }
        override fun getParentPath(): String? = null
    }
}

class ImportResolver {
    private val loadedModules = mutableSetOf<String>()
    private val allDeclarations = mutableListOf<Decl>()

    fun resolve(filePath: String, baseDir: String? = null) {
        val source = resolveSource(filePath, baseDir)
        val moduleKey = when (source) {
            is ModuleSource.FileSource -> source.file.absolutePath
            is ModuleSource.ResourceSource -> source.path
        }

        if (moduleKey in loadedModules) {
            return
        }
        loadedModules.add(moduleKey)

        val content = source.readContent()
        val fileName = when (source) {
            is ModuleSource.FileSource -> source.file.name
            is ModuleSource.ResourceSource -> source.path
        }
        val tokens = Tokenizer.tokenize(content, fileName)
        val parser = Parser(tokens)
        val program = parser.parse()

        for (decl in program.declarations) {
            if (decl is ImportDecl) {
                val importPath = decl.path
                val currentDir = source.getParentPath()
                resolve(importPath, currentDir)
            } else {
                allDeclarations.add(decl)
            }
        }
    }

    private fun resolveSource(filePath: String, baseDir: String?): ModuleSource {
        val stdlibPaths = if (filePath.endsWith(".nk")) {
            listOf("/stdlib/$filePath")
        } else {
            listOf("/stdlib/$filePath.nk", "/stdlib/$filePath")
        }
        for (stdlibPath in stdlibPaths) {
            if (javaClass.getResourceAsStream(stdlibPath) != null) {
                return ModuleSource.ResourceSource(stdlibPath)
            }
        }

        if (baseDir != null) {
            val relativeFile = File(baseDir, filePath)
            if (relativeFile.exists()) {
                return ModuleSource.FileSource(relativeFile)
            }
        }

        val file = File(filePath)
        if (file.exists()) {
            return ModuleSource.FileSource(file)
        }

        val resourcePath = if (filePath.startsWith("/")) filePath else "/$filePath"
        if (javaClass.getResourceAsStream(resourcePath) != null) {
            return ModuleSource.ResourceSource(resourcePath)
        }

        throw IllegalArgumentException(
            "Module not found: '$filePath' (tried: " +
            "1) stdlib/${filePath}.nk, " +
            "2) relative to ${baseDir ?: "(no base dir)"}, " +
            "3) absolute path, " +
            "4) resources/$filePath)"
        )
    }

    fun getProgram(): Program {
        return Program(allDeclarations, TokenInfo(null, 1, 1))
    }
}

fun main(args: Array<String>) {
    val filePath = args.firstOrNull() ?: "demo.nk"
    
    try {
        val resolver = ImportResolver()
        resolver.resolve(filePath)
        val program = resolver.getProgram()
        
        val interpreter = Interpreter()
        interpreter.interpret(program)
        interpreter.callMainIfExists()
    } catch (e: Exception) {
        println("Error: ${e.message}")
        e.printStackTrace()
    }
}
