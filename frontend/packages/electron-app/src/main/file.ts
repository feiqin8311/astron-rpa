import { spawn } from 'node:child_process'
import { mkdir } from 'node:fs/promises'

import Seven from 'node-7z'

import logger from './log'
import { d7zrPath } from './path'

export function extract7z(archivePath: string, outputDir: string, callback?: (percent: number) => void) {
  let prePercent: number = 0;

  return new Promise<void>((resolve, reject) => {
    const myStream = Seven.extractFull(archivePath, outputDir, {
      $progress: true,
      $bin: d7zrPath
    })

    myStream.on('progress', function (progress) {
      if (progress.percent === prePercent) return;

      prePercent = progress.percent;
      callback?.(prePercent)
    })

    myStream.on('end', function () {
      logger.info(`${archivePath} 解压完成`)
      resolve()
    })

    myStream.on('error', (error) => {
      logger.error(`解压错误: ${error}`)
      reject(error)
    })
  })
}

export async function extractTarGz(archivePath: string, outputDir: string, callback?: (percent: number) => void) {
  await mkdir(outputDir, { recursive: true })
  callback?.(10)

  return new Promise<void>((resolve, reject) => {
    const child = spawn('tar', ['-xzf', archivePath, '-C', outputDir])

    child.on('error', (error) => {
      logger.error(`解压错误: ${error}`)
      reject(error)
    })

    child.on('close', (code) => {
      if (code === 0) {
        logger.info(`${archivePath} 解压完成`)
        callback?.(100)
        resolve()
        return
      }
      const error = new Error(`tar exited with code ${code}`)
      logger.error(`解压错误: ${error}`)
      reject(error)
    })
  })
}
